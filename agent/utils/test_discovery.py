"""Discover test files related to a set of changed source files.

Uses fnmatch-style rules from ``test_mapping`` (in context.yaml) plus
glob-based discovery of agent-written test files to build a deduplicated,
verified list of test paths that actually exist in the sandbox.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Matches filenames that contain `.test.` or `.spec.` — the agent-written
# convention for test files (e.g. ``foo.test.js``, ``bar.spec.ts``).
_TEST_FILE_RE = re.compile(r"\.(test|spec)\.")


class Sandbox(Protocol):
    """Minimal sandbox interface required by this module."""

    def execute(self, cmd: str, timeout: int = 30) -> str: ...


def _expand_mapping_pattern(
    source_pattern: str,
    test_pattern: str,
    changed_file: str,
) -> str | None:
    """If *changed_file* matches *source_pattern*, return the concrete test path.

    Both patterns may contain ``{module}`` as a named capture group.  For
    example::

        source: "vahan_leader/{module}/**"
        test:   "test/vahan_leader/{module}/**"

    If *changed_file* is ``vahan_leader/auth/login.js`` the function
    returns ``test/vahan_leader/auth/**``.

    Returns ``None`` when the changed file does not match the source
    pattern at all.
    """
    # Build an fnmatch-compatible glob from the source pattern by
    # temporarily replacing {module} with a sentinel, then matching.
    sentinel = "__MODULE__"
    source_glob = source_pattern.replace("{module}", sentinel)

    if sentinel in source_glob:
        # We need to extract the actual module value from changed_file.
        # Convert the source pattern into a regex for that purpose.
        regex_str = _glob_to_regex_with_capture(source_pattern)
        match = re.match(regex_str, changed_file)
        if not match:
            return None
        module_value = match.group("module")
        return test_pattern.replace("{module}", module_value)

    # No {module} placeholder — plain fnmatch.
    if fnmatch.fnmatch(changed_file, source_pattern):
        return test_pattern
    return None


def _glob_to_regex_with_capture(pattern: str) -> str:
    """Convert a glob pattern with ``{module}`` into a regex with a named group.

    ``**`` maps to ``.*``, ``*`` maps to ``[^/]*``, ``{module}`` maps to
    ``(?P<module>[^/]+)``.
    """
    # Escape regex-special chars first, but preserve our placeholders.
    placeholder = "\x00MODULE\x00"
    pattern = pattern.replace("{module}", placeholder)

    # Escape everything except our placeholder and glob wildcards.
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern[i:].startswith(placeholder):
            parts.append("(?P<module>[^/]+)")
            i += len(placeholder)
        elif pattern[i:i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pattern[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pattern[i]))
            i += 1

    return "^" + "".join(parts) + "$"


def _glob_in_sandbox(sandbox: Sandbox, glob_pattern: str, repo_path: str) -> list[str]:
    """Expand a glob pattern inside the sandbox and return matching paths.

    Paths are returned relative to *repo_path*.
    """
    # Use `find` via the sandbox shell because Python's glob module
    # cannot reach into the sandbox filesystem directly.
    abs_pattern = os.path.join(repo_path, glob_pattern)
    # Use ls with the glob — shells expand globs natively.
    cmd = f"ls -1 {abs_pattern} 2>/dev/null || true"
    try:
        output = sandbox.execute(cmd, timeout=15)
    except Exception:
        logger.warning("Glob expansion failed for pattern %s", glob_pattern)
        return []

    results: list[str] = []
    prefix = repo_path.rstrip("/") + "/"
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Make relative to repo root.
        if line.startswith(prefix):
            line = line[len(prefix):]
        results.append(line)
    return results


def _file_exists_in_sandbox(sandbox: Sandbox, path: str, repo_path: str) -> bool:
    """Return True if *path* (relative to repo root) exists in the sandbox."""
    abs_path = os.path.join(repo_path, path)
    cmd = f'test -f {abs_path} && echo "EXISTS" || echo "MISSING"'
    try:
        output = sandbox.execute(cmd, timeout=10)
        return "EXISTS" in output
    except Exception:
        return False


def get_changed_files(sandbox: Sandbox, repo_path: str) -> list[str]:
    """Return the list of files changed relative to HEAD in the sandbox.

    Uses ``git diff --name-only HEAD`` which covers both staged and
    unstaged changes.  Falls back to an empty list on any error.

    Parameters
    ----------
    sandbox:
        Sandbox backend with an ``execute`` method.
    repo_path:
        Absolute path to the repo root inside the sandbox.

    Returns
    -------
    list[str]
        File paths relative to the repo root.
    """
    cmd = f"cd {repo_path} && git diff --name-only HEAD"
    try:
        output = sandbox.execute(cmd, timeout=15)
    except Exception:
        logger.warning("git diff failed in sandbox; returning empty changeset")
        return []

    files: list[str] = []
    for line in output.strip().splitlines():
        line = line.strip()
        if line:
            files.append(line)
    return files


def find_related_tests(
    changed_files: list[str],
    test_mapping: dict[str, Any],
    sandbox: Sandbox,
    repo_path: str,
) -> list[str]:
    """Discover test files relevant to a set of changed source files.

    Discovery proceeds in three passes:

    1. **Rule matching** -- each changed file is checked against every
       rule in ``test_mapping["rules"]``.  A rule that matches produces a
       glob pattern which is expanded inside the sandbox.
    2. **Agent-written tests** -- any changed file whose name contains
       ``.test.`` or ``.spec.`` is included directly (if it exists in the
       sandbox).
    3. **Fallback** -- if no tests were found via rules or agent-written
       detection, the fallback directory (``test_mapping["fallback"]``) is
       glob-searched for all files.

    Parameters
    ----------
    changed_files:
        List of file paths (relative to repo root) that were modified.
    test_mapping:
        The ``test_mapping`` section from context.yaml, containing
        ``rules`` (list of ``{source, test}`` dicts) and ``fallback``
        (directory path).
    sandbox:
        Sandbox backend.
    repo_path:
        Absolute path to the repo root inside the sandbox.

    Returns
    -------
    list[str]
        Deduplicated list of test file paths (relative to repo root) that
        exist in the sandbox.
    """
    rules: list[dict[str, str]] = test_mapping.get("rules", [])
    fallback: str = test_mapping.get("fallback", "test/")

    discovered: list[str] = []

    # --- Pass 1: rule-based matching ---
    for changed_file in changed_files:
        for rule in rules:
            source_pattern = rule.get("source", "")
            test_pattern = rule.get("test", "")
            if not source_pattern or not test_pattern:
                continue

            concrete_test_glob = _expand_mapping_pattern(
                source_pattern, test_pattern, changed_file
            )
            if concrete_test_glob is None:
                continue

            matched_files = _glob_in_sandbox(sandbox, concrete_test_glob, repo_path)
            discovered.extend(matched_files)

    # --- Pass 2: agent-written test files ---
    for changed_file in changed_files:
        if _TEST_FILE_RE.search(os.path.basename(changed_file)):
            if _file_exists_in_sandbox(sandbox, changed_file, repo_path):
                discovered.append(changed_file)

    # --- Pass 3: fallback ---
    if not discovered and fallback:
        fallback_glob = os.path.join(fallback.rstrip("/"), "**")
        fallback_files = _glob_in_sandbox(sandbox, fallback_glob, repo_path)
        # Only keep files that look like tests (by extension or naming).
        for f in fallback_files:
            basename = os.path.basename(f)
            if _TEST_FILE_RE.search(basename) or basename.startswith("test"):
                discovered.append(f)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for path in discovered:
        if path not in seen:
            seen.add(path)
            unique.append(path)

    return unique
