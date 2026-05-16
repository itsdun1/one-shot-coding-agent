import logging
import os

from deepagents.backends import LocalShellBackend

logger = logging.getLogger(__name__)


def _mint_github_token() -> str | None:
    """Mint a fresh GitHub App installation token for sandbox use (sync)."""
    try:
        import time
        import httpx
        import jwt

        app_id = os.environ.get("GITHUB_APP_ID", "")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

        if not app_id or not private_key or not installation_id:
            logger.warning("GitHub App env vars not configured, skipping token mint")
            return None

        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
        app_jwt = jwt.encode(payload, private_key, algorithm="RS256")

        resp = httpx.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        token = resp.json().get("token")
        logger.info("Minted fresh GitHub App installation token for local sandbox")
        return token
    except Exception as exc:
        logger.warning("Failed to mint GitHub token for local sandbox: %s", exc)
        return None


def create_local_sandbox(sandbox_id: str | None = None):
    """Create a local shell sandbox with no isolation.

    WARNING: This runs commands directly on the host machine with no sandboxing.
    Only use for local development with human-in-the-loop enabled.

    The root directory defaults to the current working directory and can be
    overridden via the LOCAL_SANDBOX_ROOT_DIR environment variable.

    For GitHub operations, a fresh installation token is minted and set as
    GH_TOKEN so that ``GH_TOKEN=dummy gh`` commands work without a proxy.

    Args:
        sandbox_id: Ignored for local sandboxes; accepted for interface compatibility.

    Returns:
        LocalShellBackend instance implementing SandboxBackendProtocol.
    """
    root_dir = os.getenv("LOCAL_SANDBOX_ROOT_DIR", os.getcwd())

    # Mint a fresh GitHub token so gh CLI works without proxy
    if not os.environ.get("GH_TOKEN") or os.environ.get("GH_TOKEN") == "dummy":
        token = _mint_github_token()
        if token:
            os.environ["GH_TOKEN"] = token

    return LocalShellBackend(
        root_dir=root_dir,
        inherit_env=True,
    )
