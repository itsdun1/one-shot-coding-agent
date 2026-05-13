"""Rank files by relevance to a set of keywords.

Scoring heuristic (per file, summed across all keywords):

    +10  keyword appears in the **filename** (basename)
     +5  keyword appears in a **directory segment** of the path
     +3  file matches an entry-point pattern (index.*, main.*, app.*, routes.*)
     -3  file is a constants / translations / i18n / fixture file
     -5  file lives under a test / __tests__ / spec directory or has
         .test. / .spec. / _test. in its name

The scores are deliberately coarse -- the goal is a rough ordering that
puts "obviously relevant" files at the top, not a precision ranking.
"""

from __future__ import annotations

import os
import re
from typing import List

# Basename patterns that indicate an entry point.
_ENTRY_POINT_RE = re.compile(
    r"^(?:index|main|app|server|routes|router|handler|controller)\b",
    re.IGNORECASE,
)

# Path segments or basenames that indicate low-value files.
_LOW_VALUE_SEGMENTS: frozenset[str] = frozenset(
    {
        "constants",
        "constant",
        "translations",
        "translation",
        "i18n",
        "locales",
        "locale",
        "fixtures",
        "fixture",
        "snapshots",
        "__snapshots__",
        "mocks",
        "__mocks__",
        "stubs",
        "seeds",
        "seed",
    }
)

# Patterns in filenames that signal test files.
_TEST_FILENAME_RE = re.compile(
    r"[._-](?:test|spec|e2e|integration)[._-]",
    re.IGNORECASE,
)

# Directory segments that signal test directories.
_TEST_DIR_SEGMENTS: frozenset[str] = frozenset(
    {
        "test",
        "tests",
        "__tests__",
        "spec",
        "specs",
        "e2e",
        "cypress",
        "playwright",
    }
)


def _score_file(filepath: str, keywords: list[str]) -> int:
    """Compute an integer relevance score for *filepath* against *keywords*.

    Higher is better.  The score can go negative for clearly irrelevant
    files (test fixtures, translation bundles, etc.).
    """
    basename = os.path.basename(filepath).lower()
    # Normalised directory segments (lowercase).
    dir_segments = {seg.lower() for seg in filepath.replace("\\", "/").split("/") if seg}

    score = 0

    # --- keyword matches ---
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in basename:
            score += 10
        elif any(kw_lower in seg for seg in dir_segments):
            score += 5

    # --- structural bonuses ---
    name_no_ext = os.path.splitext(basename)[0]
    if _ENTRY_POINT_RE.match(name_no_ext):
        score += 3

    # --- structural penalties ---
    if dir_segments & _LOW_VALUE_SEGMENTS or any(
        seg in basename for seg in _LOW_VALUE_SEGMENTS
    ):
        score -= 3

    if _TEST_FILENAME_RE.search(basename) or (dir_segments & _TEST_DIR_SEGMENTS):
        score -= 5

    return score


def rank_files(files: list[str], keywords: list[str]) -> list[str]:
    """Sort *files* by descending relevance to *keywords*.

    Args:
        files: Absolute or relative file paths returned by ripgrep / find.
        keywords: Lowercased keywords from ``extract_keywords``.

    Returns:
        A new list of file paths, highest-score first.  Files with the same
        score are kept in their original order (stable sort).
    """
    if not files or not keywords:
        return list(files)

    scored: list[tuple[int, int, str]] = []
    for idx, fp in enumerate(files):
        s = _score_file(fp, keywords)
        # Use (negative score, original index) so that ``sorted`` gives us
        # descending score with stable tie-breaking.
        scored.append((-s, idx, fp))

    scored.sort()
    return [fp for _, _, fp in scored]
