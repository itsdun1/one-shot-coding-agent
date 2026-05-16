"""Pre-filter middleware for the Open SWE agent framework.

An ``@before_model`` hook that runs on the **first LLM turn only**.  It
extracts keywords from the task description, runs ripgrep inside the
sandbox to locate matching files, ranks them by relevance, and injects a
rich context summary as a ``SystemMessage`` so the agent starts with a
head start rather than a blank slate.

**Critical design principle -- ADDITIVE, NOT RESTRICTIVE.**
The agent retains full access to grep / glob / read.  This middleware
merely front-loads the most likely relevant files so the agent wastes
fewer early turns on orientation.

Fallback behaviour:
    * 3+ files matched   -> full context  (files + signatures + git log)
    * 1-2 files matched  -> partial context + note to search more broadly
    * 0 files matched    -> directory skeleton (``find`` maxdepth 3)
    * no keywords at all -> ``None`` (no injection, no side effects)
"""

from __future__ import annotations

import logging
import textwrap
from typing import Any, Optional, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.utils.file_ranker import rank_files
from agent.utils.keyword_extract import extract_keywords

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# External helpers -- assumed to exist elsewhere in the codebase.
# ---------------------------------------------------------------------------
from agent.utils.sandbox_state import get_sandbox_backend_sync as get_sandbox_backend
from agent.utils.sandbox_paths import resolve_sandbox_work_dir as resolve_repo_path


def count_human_messages(messages: list) -> int:
    """Count the number of human/user messages in the conversation."""
    return sum(1 for m in messages if getattr(m, "type", None) == "human")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Maximum files to include in the injected context.
MAX_FILES: int = 30

#: How many git-log entries to include.
GIT_LOG_LIMIT: int = 20

#: Maximum number of function/class signatures to extract per file.
MAX_SIGNATURES_PER_FILE: int = 15

#: Timeout (seconds) for sandbox commands.
CMD_TIMEOUT: int = 15

#: Threshold for "good match" vs "partial match".
GOOD_MATCH_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Pattern builders
# ---------------------------------------------------------------------------

def build_rg_pattern(keywords: list[str]) -> str:
    """Build a ripgrep-compatible OR pattern from *keywords*.

    Each keyword is treated as a case-insensitive literal.  The resulting
    pattern is suitable for ``rg -e <pattern>``.

    Example::

        >>> build_rg_pattern(["leadScoring", "payout"])
        'leadScoring|payout'
    """
    # Escape regex metacharacters so keywords are matched literally.
    import re

    escaped = [re.escape(kw) for kw in keywords]
    return "|".join(escaped)


# ---------------------------------------------------------------------------
# Sandbox command helpers
# ---------------------------------------------------------------------------

def _run(sandbox: Any, cmd: str, timeout: int = CMD_TIMEOUT) -> str:
    """Execute *cmd* in the sandbox and return stdout, swallowing errors.

    Returns an empty string when the command fails or times out so that
    callers never have to guard against ``None``.
    """
    try:
        result = sandbox.execute(cmd, timeout=timeout)
        # The sandbox result object exposes `stdout` / `output` depending
        # on the backend.  Try the most common attribute names.
        out: str = getattr(result, "stdout", None) or getattr(result, "output", "") or ""
        return out.strip()
    except Exception:
        logger.debug("Sandbox command failed: %s", cmd, exc_info=True)
        return ""


def _find_files_rg(sandbox: Any, repo_path: str, pattern: str) -> list[str]:
    """Use ripgrep to find files whose *contents* match *pattern*."""
    cmd = (
        f"rg --files-with-matches --no-messages -i "
        f"-g '!node_modules' -g '!.git' -g '!dist' -g '!build' "
        f"-g '!vendor' -g '!__pycache__' -g '!*.min.*' -g '!*.map' "
        f"-g '!package-lock.json' -g '!yarn.lock' "
        f"-e '{pattern}' {repo_path}"
    )
    raw = _run(sandbox, cmd)
    if not raw:
        return []
    return [line for line in raw.splitlines() if line]


def _find_files_by_name(sandbox: Any, repo_path: str, keywords: list[str]) -> list[str]:
    """Use ``find`` to locate files whose *names* match any keyword."""
    name_clauses = " -o ".join(
        f"-iname '*{kw}*'" for kw in keywords[:5]
    )
    cmd = (
        f"find {repo_path} -maxdepth 8 "
        f"\\( -path '*/node_modules' -o -path '*/.git' -o -path '*/dist' "
        f"-o -path '*/build' -o -path '*/vendor' -o -path '*/__pycache__' \\) -prune "
        f"-o -type f \\( {name_clauses} \\) -print"
    )
    raw = _run(sandbox, cmd)
    if not raw:
        return []
    return [line for line in raw.splitlines() if line]


def _extract_signatures(sandbox: Any, filepath: str) -> str:
    """Extract function / class signatures from *filepath*.

    Uses grep for ``def ``, ``class ``, ``function ``, ``export``,
    ``const.*=.*=>``, ``module.exports``.  Returns at most
    ``MAX_SIGNATURES_PER_FILE`` lines.
    """
    patterns = (
        r"^\s*\(export\s\+\)\?\(default\s\+\)\?\(async\s\+\)\?\(function\|class\)\s"
        r"\|^\s*\(const\|let\|var\)\s\+\w\+\s*=\s*\(async\s\+\)\?("
        r"\|^\s*module\.exports"
        r"\|^\s*\(export\s\+\)\?\(default\s\+\)\?def\s"
        r"\|^\s*\(export\s\+\)\?\(default\s\+\)\?class\s"
    )
    cmd = (
        f"grep -n -E "
        f"'(^\\s*(export\\s+)?(default\\s+)?(async\\s+)?(function|class)\\s)"
        f"|(^\\s*(const|let|var)\\s+\\w+\\s*=\\s*(async\\s+)?\\()"
        f"|(^\\s*module\\.exports)"
        f"|(^\\s*(export\\s+)?(default\\s+)?def\\s)"
        f"|(^\\s*(export\\s+)?(default\\s+)?class\\s)' "
        f"'{filepath}' | head -n {MAX_SIGNATURES_PER_FILE}"
    )
    return _run(sandbox, cmd)


def _get_git_log(sandbox: Any, repo_path: str) -> str:
    """Retrieve a compact git log (last ``GIT_LOG_LIMIT`` commits)."""
    cmd = (
        f"git -C {repo_path} log --oneline --no-decorate "
        f"-n {GIT_LOG_LIMIT} 2>/dev/null"
    )
    return _run(sandbox, cmd)


def _get_directory_skeleton(sandbox: Any, repo_path: str) -> str:
    """Return a directory tree (maxdepth 3) for orientation."""
    cmd = (
        f"find {repo_path} -maxdepth 3 "
        f"\\( -path '*/node_modules' -o -path '*/.git' -o -path '*/dist' "
        f"-o -path '*/build' -o -path '*/vendor' -o -path '*/__pycache__' \\) -prune "
        f"-o -print | head -n 200"
    )
    return _run(sandbox, cmd)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def build_rich_context(
    files: list[str],
    sandbox: Any,
    repo_path: str,
    keywords: list[str],
) -> str:
    """Build a full context block for a good match (3+ files).

    Includes:
        * Ranked file list
        * Function / class signatures for the top files
        * Recent git log
    """
    sections: list[str] = []

    sections.append("## Pre-filter: Likely Relevant Files")
    sections.append(
        "The following files were identified as potentially relevant to "
        "your task based on keyword matching.  You still have full access "
        "to the entire repository -- treat this as a starting point, not a "
        "constraint.\n"
    )

    # File list
    sections.append("### Matched Files (ranked by relevance)")
    for i, fp in enumerate(files, 1):
        sections.append(f"  {i}. {fp}")

    # Signatures for top files (cap to avoid overwhelming context)
    sig_files = files[:10]
    sig_parts: list[str] = []
    for fp in sig_files:
        sigs = _extract_signatures(sandbox, fp)
        if sigs:
            sig_parts.append(f"**{fp}**\n```\n{sigs}\n```")
    if sig_parts:
        sections.append("\n### Key Signatures")
        sections.append("\n".join(sig_parts))

    # Git log
    git_log = _get_git_log(sandbox, repo_path)
    if git_log:
        sections.append("\n### Recent Commits")
        sections.append(f"```\n{git_log}\n```")

    sections.append(
        "\n### Keywords Used for Search\n"
        + ", ".join(f"`{kw}`" for kw in keywords)
    )

    return "\n".join(sections)


def build_partial_context(
    files: list[str],
    sandbox: Any,
    repo_path: str,
    keywords: list[str],
) -> str:
    """Build a reduced context block for a partial match (1-2 files).

    Includes the matched files plus a note to search more broadly.
    """
    sections: list[str] = []

    sections.append("## Pre-filter: Partial Match")
    sections.append(
        "Only a few files matched the extracted keywords.  The matches "
        "are listed below, but you should **search more broadly** before "
        "concluding these are the only relevant files.\n"
    )

    sections.append("### Matched Files")
    for i, fp in enumerate(files, 1):
        sigs = _extract_signatures(sandbox, fp)
        sections.append(f"  {i}. {fp}")
        if sigs:
            sections.append(f"```\n{sigs}\n```")

    git_log = _get_git_log(sandbox, repo_path)
    if git_log:
        sections.append("\n### Recent Commits")
        sections.append(f"```\n{git_log}\n```")

    sections.append(
        "\n### Note\n"
        "The keyword search returned very few results.  Consider using "
        "`grep`, `glob`, or `find` with broader patterns to locate "
        "additional relevant code."
    )

    sections.append(
        "\n### Keywords Used for Search\n"
        + ", ".join(f"`{kw}`" for kw in keywords)
    )

    return "\n".join(sections)


def build_skeleton_context(sandbox: Any, repo_path: str, keywords: list[str]) -> str:
    """Build an orientation-only context when no files matched.

    Injects the directory skeleton so the agent can navigate manually.
    """
    skeleton = _get_directory_skeleton(sandbox, repo_path)

    sections: list[str] = [
        "## Pre-filter: No File Matches",
        "No files matched the extracted keywords.  Here is the repository "
        "structure to help you orient:\n",
        f"```\n{skeleton}\n```",
        "\nUse `grep`, `glob`, or `find` to locate the relevant code.",
        "\n### Keywords Attempted\n"
        + ", ".join(f"`{kw}`" for kw in keywords),
    ]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# The middleware itself
# ---------------------------------------------------------------------------

def before_model(messages: list[BaseMessage], **kwargs: Any) -> Optional[list[BaseMessage]]:
    """``@before_model`` hook -- pre-filter context injection.

    Runs **only on the first human message**.  On subsequent turns the
    function returns ``None`` (no-op) so the agent proceeds normally.

    Args:
        messages: The current message list handed to the model.
        **kwargs: Extra keyword arguments forwarded by the framework.

    Returns:
        An augmented message list with a ``SystemMessage`` prepended
        containing the pre-filter context, or ``None`` when the hook
        decides not to inject anything.
    """
    # ---- guard: first turn only ----
    human_count = count_human_messages(messages)
    if human_count != 1:
        return None

    # ---- extract the task text from the first human message ----
    task_text: Optional[str] = None
    for msg in messages:
        if isinstance(msg, HumanMessage):
            task_text = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not task_text:
        return None

    # ---- keyword extraction ----
    keywords = extract_keywords(task_text)
    if not keywords:
        logger.info("Pre-filter: no keywords extracted, skipping injection.")
        return None

    logger.info("Pre-filter: extracted keywords: %s", keywords)

    # ---- obtain sandbox ----
    try:
        from langgraph.config import get_config

        config = get_config()
        thread_id: str = config["configurable"].get("thread_id", "")
    except Exception:
        logger.warning("Pre-filter: could not retrieve thread config, skipping.")
        return None

    if not thread_id:
        return None

    try:
        sandbox = get_sandbox_backend(thread_id)
    except Exception:
        logger.warning("Pre-filter: sandbox not available for thread %s", thread_id)
        return None

    try:
        repo_path = resolve_repo_path(sandbox)
    except Exception:
        logger.warning("Pre-filter: could not resolve repo path, skipping.")
        return None

    # ---- search for files ----
    rg_pattern = build_rg_pattern(keywords)

    # Two search strategies: content match (ripgrep) + filename match (find).
    content_files = _find_files_rg(sandbox, repo_path, rg_pattern)
    name_files = _find_files_by_name(sandbox, repo_path, keywords)

    # Merge and deduplicate while preserving order.
    seen: set[str] = set()
    merged: list[str] = []
    for fp in content_files + name_files:
        if fp not in seen:
            seen.add(fp)
            merged.append(fp)

    # Rank and cap.
    ranked = rank_files(merged, keywords)[:MAX_FILES]

    # ---- build context ----
    if len(ranked) >= GOOD_MATCH_THRESHOLD:
        context_body = build_rich_context(ranked, sandbox, repo_path, keywords)
    elif len(ranked) >= 1:
        context_body = build_partial_context(ranked, sandbox, repo_path, keywords)
    else:
        context_body = build_skeleton_context(sandbox, repo_path, keywords)

    logger.info(
        "Pre-filter: injecting context (%d files matched, %d ranked).",
        len(merged),
        len(ranked),
    )

    # ---- inject as SystemMessage at the front ----
    context_message = SystemMessage(content=context_body)
    return [context_message] + list(messages)
