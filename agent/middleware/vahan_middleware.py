"""Vahan custom middleware — proper AgentMiddleware classes.

Wraps the pre-filter and deterministic checks as class-based middleware
compatible with Deep Agents' AgentMiddleware interface.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState

logger = logging.getLogger(__name__)


async def _slack_status(config: dict, message: str) -> None:
    """Post a progress update to the Slack thread (fire-and-forget)."""
    try:
        configurable = config.get("configurable", {})
        slack_thread = configurable.get("slack_thread") if isinstance(configurable, dict) else None
        if not isinstance(slack_thread, dict):
            return
        channel_id = slack_thread.get("channel_id", "")
        thread_ts = slack_thread.get("thread_ts", "")
        if not channel_id or not thread_ts:
            return
        from agent.integrations.slack import post_slack_thread_reply
        await post_slack_thread_reply(channel_id, thread_ts, message)
    except Exception:
        pass  # Non-critical — don't break the run


async def _exec(sandbox: Any, cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Execute a command in the sandbox asynchronously.

    Uses asyncio subprocess to avoid blocking the ASGI event loop.
    Falls back to sync execution if async is not possible.
    """
    import asyncio

    # Get pod name from sandbox
    pod_name = getattr(sandbox, '_pod_name', None)
    if pod_name:
        try:
            proc = await asyncio.create_subprocess_exec(
                "kubectl", "exec", pod_name,
                "-n", os.environ.get("SANDBOX_NAMESPACE", "vahan-agent"),
                "-c", "sandbox",
                "--", "bash", "-c", cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 10)
            output = (stdout or b"").decode() + (stderr or b"").decode()
            return proc.returncode or 0, output
        except asyncio.TimeoutError:
            return 1, f"Command timed out after {timeout}s"
        except Exception as e:
            return 1, str(e)

    # Fallback: use sandbox.execute in a thread to avoid blocking
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: sandbox.execute(cmd, timeout=timeout))
        if hasattr(result, "exit_code"):
            return result.exit_code, result.output or ""
        if hasattr(result, "returncode"):
            return result.returncode, str(result.stdout or "") + str(result.stderr or "")
        return 0, str(result)
    except Exception as e:
        return 1, str(e)


async def _get_changed_files(sandbox: Any, repo_path: str) -> list[str]:
    """Get files changed by the agent vs the base branch.

    Tries multiple strategies:
    1. git diff origin/main...HEAD (three-dot merge-base diff — works on new branches)
    2. git diff origin/dev...HEAD (some repos use dev as default)
    3. git log origin/main..HEAD --name-only (committed files only)
    4. git diff HEAD~1 (fallback — last commit only)
    5. git diff HEAD (uncommitted changes)
    """
    strategies = [
        f"cd {repo_path} && git diff --name-only origin/main...HEAD 2>/dev/null",
        f"cd {repo_path} && git diff --name-only origin/dev...HEAD 2>/dev/null",
        f"cd {repo_path} && git log --name-only --pretty=format: origin/main..HEAD 2>/dev/null",
        f"cd {repo_path} && git diff --name-only HEAD~1 2>/dev/null",
        f"cd {repo_path} && git diff --name-only HEAD 2>/dev/null",
    ]

    for strategy in strategies:
        ec, output = await _exec(sandbox, strategy)
        if ec == 0 and output.strip():
            files = [
                f.strip() for f in output.strip().split("\n")
                if f.strip() and f.strip().endswith(('.js', '.ts', '.jsx', '.tsx', '.py'))
            ]
            if files:
                # Deduplicate (git log can list same file multiple times)
                return list(dict.fromkeys(files))

    return []


async def _parse_context_yaml(sandbox: Any, repo_path: str) -> dict:
    """Read and parse context.yaml from the repo root. Returns empty dict on failure."""
    ec, content = await _exec(sandbox, f"cat {repo_path}/context.yaml 2>/dev/null")
    if ec != 0 or not content.strip():
        return {}
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except Exception:
        # Fallback: extract lint command with regex if yaml not available
        result = {}
        lint_match = re.search(r'lint:\s*\n\s*command:\s*["\']?(.+?)["\']?\s*\n', content)
        if lint_match:
            result["lint"] = {"command": lint_match.group(1)}
        autofix_match = re.search(r'autofix:\s*["\']?(.+?)["\']?\s*\n', content)
        if autofix_match:
            result.setdefault("lint", {})["autofix"] = autofix_match.group(1)
        return result


class PreFilterMiddleware(AgentMiddleware):
    """Injects pre-filtered context on the first model call.

    Runs keyword extraction → ripgrep → file ranking → injects
    top files + signatures as a SystemMessage. Additive — the agent
    retains full tool access for anything the pre-filter missed.
    """

    state_schema = AgentState
    _injected = False

    def before_model(self, state: Any, runtime: Any) -> dict | None:
        if self._injected:
            return None
        self._injected = True

        try:
            from agent.middleware.prefilter_context import before_model as _prefilter
            messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
            result = _prefilter(messages)
            if result is not None:
                logger.info("Pre-filter injected context")
                return {"messages": result}
        except Exception as e:
            logger.warning("Pre-filter failed (non-fatal): %s", e)

        return None


class DeterministicChecksMiddleware(AgentMiddleware):
    """Runs deterministic validation after the agent finishes.

    Tier 1 — Syntax check (node -c / python -m py_compile)
    Tier 2 — Pattern checks (debug artifacts, credentials, leftover patterns)
    Tier 3 — Lint (from context.yaml or fallback eslint)
    Tier 4 — Cleanup (smoke test files removed)

    All checks use zero external packages — only built-in tools.
    If checks fail, feeds errors back to agent for 1 retry.
    """

    state_schema = AgentState
    _checks_run = False

    async def aafter_agent(self, state: Any, runtime: Any) -> dict | None:
        """Async after_agent hook — runs deterministic checks."""
        if self._checks_run:
            return None
        self._checks_run = True

        try:
            from langgraph.config import get_config
            config = get_config()
            thread_id = config.get("configurable", {}).get("thread_id", "")

            from agent.utils.sandbox_state import SANDBOX_BACKENDS
            sandbox = SANDBOX_BACKENDS.get(thread_id)
            if sandbox is None:
                logger.info("No cached sandbox for thread %s, skipping checks", thread_id)
                return None
            # Unwrap proxy if needed
            if hasattr(sandbox, '_backend'):
                sandbox = sandbox._backend

            # Find repo path
            exit_code, output = await _exec(sandbox, "ls /workspace/")
            repo_dirs = [d for d in output.strip().split("\n") if d and not d.startswith(".")]
            if not repo_dirs:
                logger.info("No repo found in sandbox, skipping checks")
                return None
            repo_path = f"/workspace/{repo_dirs[0]}"

            # Get changed files using multi-strategy detection
            changed_files = await _get_changed_files(sandbox, repo_path)

            if not changed_files:
                logger.info("No changed files detected, skipping checks")
                return None

            logger.info("Deterministic checks on %d files: %s", len(changed_files), changed_files)
            await _slack_status(config, f"Running automated checks on {len(changed_files)} changed file(s)...")

            # Parse context.yaml for repo-specific commands
            ctx = await _parse_context_yaml(sandbox, repo_path)

            errors = []
            warnings = []

            # ── Tier 1: Syntax check ──
            for f in changed_files:
                # Verify file exists (may have been deleted)
                ec_exists, _ = await _exec(sandbox, f"test -f {repo_path}/{f}")
                if ec_exists != 0:
                    continue

                if f.endswith(('.js', '.jsx')):
                    ec, out = await _exec(sandbox, f"cd {repo_path} && node -c {f} 2>&1")
                    if ec != 0:
                        errors.append(f"SYNTAX ERROR in {f}:\n{out[:500]}")
                elif f.endswith('.py'):
                    ec, out = await _exec(sandbox, f"cd {repo_path} && python -m py_compile {f} 2>&1")
                    if ec != 0:
                        errors.append(f"SYNTAX ERROR in {f}:\n{out[:500]}")

            # ── Tier 2: Pattern checks (zero deps, read file content) ──
            for f in changed_files:
                ec, src = await _exec(sandbox, f"cd {repo_path} && cat {f} 2>/dev/null")
                if ec != 0:
                    continue

                # Hardcoded credentials
                for pattern in ["password='", 'password="', "apiKey='", "secret='", "token='", "apikey="]:
                    idx = src.find(pattern)
                    if idx != -1:
                        context = src[max(0, idx - 50):idx + 50]
                        if "process.env" not in context and "config" not in context.lower():
                            warnings.append(f"{f}: possible hardcoded credential near '{pattern}'")
                            break

                # Check diff for logger migration completeness
                ec2, diff = await _exec(sandbox, f"cd {repo_path} && git diff HEAD~1 -- {f} 2>/dev/null")
                if ec2 == 0 and ("logger.info" in diff or "logger.error" in diff):
                    remaining = len(re.findall(r"console\.(log|error)\(", src))
                    if remaining > 0:
                        warnings.append(f"{f}: {remaining} console.log/error still remain after logger migration")

            # ── Tier 3: Lint (context.yaml-driven or fallback) ──
            js_files = [f for f in changed_files if f.endswith(('.js', '.jsx', '.ts', '.tsx'))]
            if js_files:
                files_str = " ".join(js_files)
                lint_cmd = None
                autofix_cmd = None

                # Try context.yaml first
                lint_config = ctx.get("lint", {})
                if lint_config:
                    raw_cmd = lint_config.get("command", "")
                    raw_autofix = lint_config.get("autofix", "")
                    if raw_cmd:
                        lint_cmd = raw_cmd.replace("{changed_files}", files_str)
                    if raw_autofix:
                        autofix_cmd = raw_autofix.replace("{changed_files}", files_str)

                # Run autofix first if available
                if autofix_cmd:
                    logger.info("Running lint autofix: %s", autofix_cmd)
                    await _exec(sandbox, f"cd {repo_path} && {autofix_cmd}", timeout=60)
                    # Stage autofix changes
                    await _exec(sandbox, f"cd {repo_path} && git add -A && git commit -m 'chore: autofix lint' --allow-empty 2>/dev/null")

                # Run lint check
                if lint_cmd:
                    logger.info("Running lint: %s", lint_cmd)
                    ec, out = await _exec(sandbox, f"cd {repo_path} && {lint_cmd} 2>&1", timeout=60)
                    if ec != 0 and out.strip():
                        errors.append(f"LINT ERRORS:\n{out[:1500]}")
                else:
                    # Fallback: basic eslint with no-undef only
                    ec, _ = await _exec(sandbox, "which npx 2>/dev/null")
                    if ec == 0:
                        ec, out = await _exec(sandbox,
                            f"cd {repo_path} && npx eslint --no-eslintrc "
                            f"--rule '{{\"no-undef\": \"error\"}}' "
                            f"{files_str} 2>&1",
                            timeout=30
                        )
                        if ec != 0 and "error" in out.lower():
                            errors.append(f"LINT ERRORS:\n{out[:1000]}")

            # ── Tier 4: Cleanup check ──
            ec, out = await _exec(sandbox, f"cd {repo_path} && ls _smoke_test* 2>/dev/null")
            if ec == 0 and out.strip():
                errors.append("_smoke_test* file left behind — delete before committing")

            # ── Report ──
            if errors:
                error_msg = "\n\n".join(errors)
                warning_msg = "\n".join(warnings) if warnings else ""
                full_msg = (
                    f"Automated checks found {len(errors)} error(s). "
                    f"Fix before creating PR (1 attempt):\n\n{error_msg[:2000]}"
                )
                if warning_msg:
                    full_msg += f"\n\nWarnings (non-blocking):\n{warning_msg[:500]}"

                logger.warning("Checks: %d errors, %d warnings", len(errors), len(warnings))
                from langchain_core.messages import HumanMessage
                messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
                return {"messages": [*messages, HumanMessage(content=full_msg)]}

            if warnings:
                logger.info("Checks passed with %d warnings: %s", len(warnings), warnings)
                await _slack_status(config, f"Automated checks passed with {len(warnings)} warning(s).")
            else:
                logger.info("All deterministic checks passed")
                await _slack_status(config, "All automated checks passed.")
            return None

        except Exception as e:
            logger.warning("Deterministic checks failed (non-fatal): %s", e)
            return None
