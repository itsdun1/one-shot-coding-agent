"""Fargate sandbox provider — spins up a K8s pod per agent task.

Each task gets an isolated Fargate pod with:
- Pre-built sandbox image (Node, git, gh CLI)
- Fresh GitHub App installation token as GH_TOKEN
- Dedicated workspace, auto-cleaned on completion

The orchestrator communicates with the sandbox pod via kubectl exec.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import ExecuteResponse

logger = logging.getLogger(__name__)

SANDBOX_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "vahan-agent")
SANDBOX_IMAGE = os.environ.get(
    "SANDBOX_IMAGE",
    "091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/sandbox:latest",
)
SANDBOX_CPU = os.environ.get("SANDBOX_CPU", "500m")
SANDBOX_MEMORY = os.environ.get("SANDBOX_MEMORY", "1Gi")
SANDBOX_TTL_SECONDS = int(os.environ.get("SANDBOX_TTL_SECONDS", "1800"))  # 30 min


def _mint_github_token() -> str:
    """Mint a fresh GitHub App installation token (sync)."""
    import httpx
    import jwt as pyjwt

    app_id = os.environ.get("GITHUB_APP_ID", "")
    private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
    app_jwt = pyjwt.encode(payload, private_key, algorithm="RS256")

    resp = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
        },
    )
    resp.raise_for_status()
    return resp.json()["token"]


def _create_sandbox_pod(pod_name: str, gh_token: str) -> None:
    """Create a Fargate pod for the sandbox."""
    import subprocess

    manifest = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
  namespace: {SANDBOX_NAMESPACE}
  labels:
    app: vahan-agent-sandbox
    sandbox-id: {pod_name}
spec:
  restartPolicy: Never
  activeDeadlineSeconds: {SANDBOX_TTL_SECONDS}
  containers:
    - name: sandbox
      image: {SANDBOX_IMAGE}
      command: ["/sandbox-entrypoint.sh"]
      args: ["sleep", "{SANDBOX_TTL_SECONDS}"]
      env:
        - name: GH_TOKEN
          value: "{gh_token}"
        - name: NODE_ENV
          value: "development"
        - name: REDIS_URL
          value: "redis://localhost:6379"
        - name: DATABASE_URL
          value: "postgresql://test:test@localhost:5432/testdb"
        - name: RABBITMQ_URL
          value: "amqp://localhost:5672"
        - name: SENTRY_DSN
          value: ""
        - name: ELASTIC_APM_ACTIVE
          value: "false"
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: vahan-agent-secrets
              key: AWS_ACCESS_KEY_ID
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: vahan-agent-secrets
              key: AWS_SECRET_ACCESS_KEY
        - name: AWS_DEFAULT_REGION
          valueFrom:
            secretKeyRef:
              name: vahan-agent-secrets
              key: AWS_DEFAULT_REGION
      resources:
        requests:
          cpu: "{SANDBOX_CPU}"
          memory: "{SANDBOX_MEMORY}"
        limits:
          cpu: "{SANDBOX_CPU}"
          memory: "{SANDBOX_MEMORY}"
      workingDir: /workspace
"""

    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create sandbox pod: {result.stderr}")

    logger.info("Created sandbox pod %s in namespace %s", pod_name, SANDBOX_NAMESPACE)

    # Wait for pod to be running
    for _ in range(100):  # 100 * 3s = 300s max wait (Fargate cold start + image pull)
        check = subprocess.run(
            [
                "kubectl", "get", "pod", pod_name,
                "-n", SANDBOX_NAMESPACE,
                "-o", "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        phase = check.stdout.strip()
        if phase == "Running":
            logger.info("Sandbox pod %s is running", pod_name)
            return
        if phase in ("Failed", "Unknown"):
            raise RuntimeError(f"Sandbox pod {pod_name} entered {phase} state")
        time.sleep(3)

    raise RuntimeError(f"Sandbox pod {pod_name} did not start within 300s")


def _delete_sandbox_pod(pod_name: str) -> None:
    """Delete a sandbox pod."""
    import subprocess

    subprocess.run(
        ["kubectl", "delete", "pod", pod_name, "-n", SANDBOX_NAMESPACE, "--ignore-not-found"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    logger.info("Deleted sandbox pod %s", pod_name)


class FargateSandbox(BaseSandbox):
    """Sandbox that runs as an isolated Fargate pod in the same EKS cluster."""

    def __init__(self, pod_name: str):
        self._pod_name = pod_name

    @property
    def id(self) -> str:
        return self._pod_name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Execute a command in the sandbox pod via kubectl exec."""
        import subprocess

        effective_timeout = timeout or 300
        try:
            result = subprocess.run(
                [
                    "kubectl", "exec", self._pod_name,
                    "-n", SANDBOX_NAMESPACE,
                    "-c", "sandbox",
                    "--", "bash", "-c", command,
                ],
                capture_output=True,
                text=True,
                timeout=effective_timeout + 10,  # buffer for kubectl overhead
            )
            output = result.stdout + result.stderr
            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=len(output) > 100_000,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Command timed out after {effective_timeout}s",
                exit_code=1,
                truncated=False,
            )
        except Exception as exc:
            return ExecuteResponse(
                output=f"kubectl exec failed: {exc}",
                exit_code=1,
                truncated=False,
            )

    def upload_files(self, files: list, destination: str = "/workspace") -> None:
        """Upload files to sandbox via kubectl cp."""
        import subprocess
        for f in files:
            subprocess.run(
                ["kubectl", "cp", f, f"{self._pod_name}:{destination}/", "-n", SANDBOX_NAMESPACE, "-c", "sandbox"],
                capture_output=True, text=True, timeout=60,
            )

    def download_files(self, paths: list, destination: str = ".") -> None:
        """Download files from sandbox via kubectl cp."""
        import subprocess
        for p in paths:
            subprocess.run(
                ["kubectl", "cp", f"{self._pod_name}:{p}", destination, "-n", SANDBOX_NAMESPACE, "-c", "sandbox"],
                capture_output=True, text=True, timeout=60,
            )

    def cleanup(self) -> None:
        """Delete the sandbox pod."""
        try:
            _delete_sandbox_pod(self._pod_name)
        except Exception:
            logger.exception("Failed to cleanup sandbox pod %s", self._pod_name)


def create_fargate_sandbox(sandbox_id: str | None = None) -> FargateSandbox:
    """Create a new Fargate sandbox pod or reconnect to an existing one.

    Args:
        sandbox_id: Optional existing pod name to reconnect to.

    Returns:
        FargateSandbox instance.
    """
    if sandbox_id and sandbox_id.startswith("sandbox-"):
        # Reconnect to existing pod
        logger.info("Reconnecting to existing sandbox pod %s", sandbox_id)
        return FargateSandbox(sandbox_id)

    # Cleanup old sandbox pods before creating a new one
    _cleanup_old_sandboxes()

    # Create new pod
    pod_name = f"sandbox-{uuid.uuid4().hex[:12]}"
    gh_token = _mint_github_token()
    _create_sandbox_pod(pod_name, gh_token)
    return FargateSandbox(pod_name)


def _cleanup_old_sandboxes() -> None:
    """Delete sandbox pods older than TTL. Runs on each new sandbox creation."""
    import subprocess
    import json

    try:
        result = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", SANDBOX_NAMESPACE,
                "-l", "app=vahan-agent-sandbox",
                "-o", "json",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return

        pods = json.loads(result.stdout).get("items", [])
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        for pod in pods:
            name = pod.get("metadata", {}).get("name", "")
            created = pod.get("metadata", {}).get("creationTimestamp", "")
            phase = pod.get("status", {}).get("phase", "")
            if not created:
                continue

            from datetime import datetime, timezone
            pod_age = (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds()

            # Only delete terminal-state pods (Failed/Succeeded) — running pods may have active threads
            if phase in ("Failed", "Succeeded"):
                logger.info("Cleaning up terminal sandbox pod %s (age=%ds, phase=%s)", name, int(pod_age), phase)
                subprocess.run(
                    ["kubectl", "delete", "pod", name, "-n", SANDBOX_NAMESPACE, "--ignore-not-found"],
                    capture_output=True, text=True, timeout=15,
                )
    except Exception as e:
        logger.debug("Sandbox cleanup failed (non-fatal): %s", e)
