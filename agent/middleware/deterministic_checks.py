"""After-agent middleware that runs deterministic lint and test checks.

This middleware is registered as an ``@after_agent`` hook.  It executes
**after** the coding agent has finished writing code and tests, and
performs the following pipeline:

1. Parse ``context.yaml`` from the repo root for lint/test/sandbox config.
2. Run ESLint autofix (deterministic).
3. Run the lint check command -- on failure, feed errors back to the
   agent for one retry.
4. Seed the database (run migrations) if configured.
5. Discover related test files via test_mapping rules and agent-written
   ``.test.`` / ``.spec.`` files.
6. Run tests with sandbox env vars -- on failure, feed errors back to
   the agent for one retry.
7. Store structured results (lint pass/fail, test pass/fail/skipped) for
   the PR body.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.utils.context_yaml import parse_context_yaml
from agent.utils.test_discovery import find_related_tests, get_changed_files

logger = logging.getLogger(__name__)

# Maximum characters of command output included in feedback messages.
_LINT_OUTPUT_CAP = 2000
_TEST_OUTPUT_CAP = 3000


# ---------------------------------------------------------------------------
# Sandbox / external helper protocols (provided by the host framework)
# ---------------------------------------------------------------------------

# These are imported at call-time from the host; declared here for typing.
# get_sandbox_backend(thread_id) -> sandbox
# resolve_repo_path(sandbox) -> str
# store_check_results(config, results: dict) -> None


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class CheckResults:
    """Accumulates pass/fail/skipped status for every stage."""

    lint_autofix: str = "skipped"
    lint_check: str = "skipped"
    seed_db: str = "skipped"
    tests: str = "skipped"
    test_files_run: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for ``store_check_results``."""
        return {
            "lint_autofix": self.lint_autofix,
            "lint_check": self.lint_check,
            "seed_db": self.seed_db,
            "tests": self.tests,
            "test_files_run": self.test_files_run,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cap(text: str, limit: int) -> str:
    """Truncate *text* to *limit* characters, appending an indicator."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [output truncated]"


def _build_env_prefix(env_vars: dict[str, str]) -> str:
    """Build a shell-compatible ``KEY=value`` prefix string."""
    if not env_vars:
        return ""
    parts = [f"{k}={v}" for k, v in env_vars.items()]
    return " ".join(parts) + " "


def _run_command(
    sandbox: Any,
    command: str,
    *,
    timeout: int = 120,
    env_vars: dict[str, str] | None = None,
    cwd: str | None = None,
) -> tuple[bool, str]:
    """Execute *command* in the sandbox and return ``(success, output)``.

    Parameters
    ----------
    sandbox:
        Sandbox backend.
    command:
        Shell command to run.
    timeout:
        Execution timeout in seconds.
    env_vars:
        Extra environment variables injected as a prefix.
    cwd:
        Working directory (prepended as ``cd <cwd> &&``).

    Returns
    -------
    tuple[bool, str]
        ``(True, stdout/stderr)`` on exit-code 0, ``(False, output)``
        otherwise.
    """
    prefix = _build_env_prefix(env_vars or {})
    cd_prefix = f"cd {cwd} && " if cwd else ""
    # Capture both stdout and stderr; use exit code to determine success.
    full_cmd = f"{cd_prefix}{prefix}{command}; echo __EXIT_CODE__$?"
    try:
        raw_output = sandbox.execute(full_cmd, timeout=timeout)
    except Exception as exc:
        return False, f"Command timed out or crashed: {exc}"

    # Parse exit code from the sentinel we appended.
    lines = raw_output.rsplit("__EXIT_CODE__", 1)
    output = lines[0].strip()
    try:
        exit_code = int(lines[1].strip()) if len(lines) > 1 else 1
    except (ValueError, IndexError):
        exit_code = 1

    return exit_code == 0, output


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_lint_autofix(
    sandbox: Any,
    config: dict[str, Any],
    repo_path: str,
    results: CheckResults,
) -> None:
    """Run the autofix command (e.g. ``npx eslint --fix .``).

    This stage never fails the pipeline -- autofix is best-effort.
    """
    lint_config = config.get("lint", {})
    if lint_config.get("skip", False):
        logger.info("Lint is explicitly skipped for this repo.")
        results.lint_autofix = "skipped"
        return
    autofix_cmd = lint_config.get("autofix", "")
    if not autofix_cmd:
        logger.info("No lint autofix command configured; skipping.")
        return

    # Scope to changed files only if configured
    if lint_config.get("scope") == "changed_files_only":
        changed = get_changed_files(sandbox, repo_path)
        lintable = [f for f in changed if f.endswith(('.js', '.ts', '.jsx', '.tsx'))]
        if not lintable:
            logger.info("No lintable changed files; skipping autofix.")
            results.lint_autofix = "skipped"
            return
        autofix_cmd = autofix_cmd.replace("{changed_files}", " ".join(lintable))

    logger.info("Running lint autofix: %s", autofix_cmd)
    success, output = _run_command(sandbox, autofix_cmd, cwd=repo_path)
    results.lint_autofix = "pass" if success else "fail"
    if not success:
        logger.warning("Lint autofix exited non-zero (non-fatal):\n%s", _cap(output, _LINT_OUTPUT_CAP))


def _run_lint_check(
    sandbox: Any,
    config: dict[str, Any],
    repo_path: str,
    results: CheckResults,
) -> dict[str, Any] | None:
    """Run the lint check command.  Returns a retry payload on failure."""
    lint_config = config.get("lint", {})
    if lint_config.get("skip", False):
        logger.info("Lint is explicitly skipped for this repo.")
        results.lint_check = "skipped"
        return None
    lint_cmd = lint_config.get("command", "")
    if not lint_cmd:
        logger.info("No lint check command configured; skipping.")
        return None

    # Scope to changed files only if configured
    if lint_config.get("scope") == "changed_files_only":
        changed = get_changed_files(sandbox, repo_path)
        lintable = [f for f in changed if f.endswith(('.js', '.ts', '.jsx', '.tsx'))]
        if not lintable:
            logger.info("No lintable changed files; skipping lint check.")
            results.lint_check = "skipped"
            return None
        lint_cmd = lint_cmd.replace("{changed_files}", " ".join(lintable))

    logger.info("Running lint check: %s", lint_cmd)
    success, output = _run_command(sandbox, lint_cmd, cwd=repo_path)
    if success:
        results.lint_check = "pass"
        return None

    results.lint_check = "fail"
    return {
        "stage": "lint",
        "message": (
            "Lint check failed. Fix the following errors and try again:\n\n"
            f"```\n{_cap(output, _LINT_OUTPUT_CAP)}\n```"
        ),
    }


def _run_seed_db(
    sandbox: Any,
    config: dict[str, Any],
    repo_path: str,
    results: CheckResults,
) -> bool:
    """Run the database seed/migration command if configured.

    Returns True if seeding succeeded or was not configured, False on
    failure.
    """
    seed_cmd = config.get("sandbox", {}).get("seed", "")
    if not seed_cmd:
        logger.info("No DB seed command configured; skipping.")
        return True

    env_vars: dict[str, str] = config.get("sandbox", {}).get("env", {})
    logger.info("Seeding database: %s", seed_cmd)
    success, output = _run_command(
        sandbox, seed_cmd, cwd=repo_path, env_vars=env_vars, timeout=180,
    )
    results.seed_db = "pass" if success else "fail"
    if not success:
        logger.error("DB seed failed:\n%s", _cap(output, _LINT_OUTPUT_CAP))
    return success


def _run_tests(
    sandbox: Any,
    config: dict[str, Any],
    repo_path: str,
    test_files: list[str],
    results: CheckResults,
) -> dict[str, Any] | None:
    """Run the test suite.  Returns a retry payload on failure."""
    if not test_files:
        logger.info("No test files discovered; marking tests as skipped.")
        results.tests = "skipped"
        return None

    env_vars: dict[str, str] = config.get("sandbox", {}).get("env", {})
    selective_cmd_template: str = config.get("test", {}).get("selective", "")
    fallback_cmd: str = config.get("test", {}).get("command", "")

    results.test_files_run = list(test_files)

    # Prefer selective test runner if configured.
    if selective_cmd_template:
        test_file_arg = " ".join(test_files)
        test_cmd = selective_cmd_template.replace("{test_file}", test_file_arg)
    elif fallback_cmd:
        test_cmd = fallback_cmd
    else:
        logger.info("No test command configured; skipping.")
        results.tests = "skipped"
        return None

    logger.info("Running tests: %s", test_cmd)
    success, output = _run_command(
        sandbox, test_cmd, cwd=repo_path, env_vars=env_vars, timeout=300,
    )
    if success:
        results.tests = "pass"
        return None

    results.tests = "fail"
    return {
        "stage": "test",
        "message": (
            "Tests failed. Fix the following failures and try again:\n\n"
            f"```\n{_cap(output, _TEST_OUTPUT_CAP)}\n```"
        ),
    }


# ---------------------------------------------------------------------------
# Public API -- the after_agent hook
# ---------------------------------------------------------------------------

def after_agent(func: Any) -> Any:
    """Decorator stub matching the host framework's ``@after_agent`` hook.

    In production the real decorator is provided by the agent framework.
    This implementation simply returns the wrapped function so that the
    module can be imported and tested independently.
    """
    return func


@after_agent
async def deterministic_checks(config: Any, state: dict[str, Any]) -> dict[str, Any] | None:
    """Run deterministic lint and test checks after the agent finishes.

    Parameters
    ----------
    config:
        LangGraph ``RunnableConfig`` carrying ``thread_id`` and any
        host-level settings.
    state:
        Current agent state dict (not mutated by this middleware).

    Returns
    -------
    dict | None
        If a stage fails and a retry is warranted, returns a dict with
        ``stage`` and ``message`` keys that the framework feeds back to
        the agent.  Returns ``None`` on full success (results are stored
        via ``store_check_results`` instead).
    """
    # Late imports so the module can be unit-tested without the full
    # framework installed.
    from agent.utils.sandbox_helpers import (  # type: ignore[import-untyped]
        get_sandbox_backend,
        resolve_repo_path,
        store_check_results,
    )

    thread_id: str = config.get("configurable", {}).get("thread_id", "")
    sandbox = get_sandbox_backend(thread_id)
    repo_path = resolve_repo_path(sandbox)

    # -- Load context.yaml -------------------------------------------------
    try:
        context_raw: str = sandbox.read(f"{repo_path}/context.yaml")
    except Exception:
        logger.warning("context.yaml not found; using defaults.")
        context_raw = ""

    ctx = parse_context_yaml(context_raw)
    results = CheckResults()

    # -- Stage 1: Lint autofix (best-effort) --------------------------------
    _run_lint_autofix(sandbox, ctx, repo_path, results)

    # -- Stage 2: Lint check (1 retry) --------------------------------------
    lint_failure = _run_lint_check(sandbox, ctx, repo_path, results)
    if lint_failure is not None:
        # Give the agent one chance to fix lint errors.
        store_check_results(config, results.to_dict())
        return lint_failure

    # -- Stage 3: Seed DB ---------------------------------------------------
    seed_ok = _run_seed_db(sandbox, ctx, repo_path, results)
    if not seed_ok:
        # DB seed failure is not retried by the agent -- it is an infra
        # issue.  Store results and let the pipeline continue without tests.
        logger.error("DB seed failed; skipping test execution.")
        results.tests = "skipped"
        store_check_results(config, results.to_dict())
        return None

    # -- Stage 4: Discover test files ---------------------------------------
    changed_files = get_changed_files(sandbox, repo_path)
    test_mapping: dict[str, Any] = ctx.get("test_mapping", {})
    test_files = find_related_tests(changed_files, test_mapping, sandbox, repo_path)
    logger.info("Discovered %d test file(s): %s", len(test_files), test_files)

    # -- Stage 5: Run tests (1 retry) ---------------------------------------
    test_failure = _run_tests(sandbox, ctx, repo_path, test_files, results)
    if test_failure is not None:
        store_check_results(config, results.to_dict())
        return test_failure

    # -- All green ----------------------------------------------------------
    store_check_results(config, results.to_dict())
    logger.info("All deterministic checks passed.")
    return None
