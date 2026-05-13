"""Keyword extraction from task descriptions.

Pure text processing -- no LLM calls.  Splits on whitespace and punctuation,
expands camelCase / PascalCase tokens, removes stop words, deduplicates, and
caps the result at 10 keywords sorted by descending length (longer = more
specific = more useful for ripgrep).
"""

from __future__ import annotations

import re
from typing import List

# Common English stop words + programming noise words that hurt search recall.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        # determiners / pronouns / prepositions
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "us",
        # conjunctions / connectors
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "when",
        "while",
        "for",
        "of",
        "in",
        "on",
        "at",
        "to",
        "by",
        "with",
        "from",
        "as",
        "into",
        "about",
        "so",
        "not",
        "no",
        "do",
        "does",
        "did",
        "will",
        "would",
        "should",
        "could",
        "can",
        "may",
        "might",
        "shall",
        "has",
        "have",
        "had",
        "just",
        "also",
        "very",
        "too",
        "only",
        "than",
        "more",
        "most",
        "some",
        "any",
        "all",
        "each",
        "every",
        "both",
        "such",
        "here",
        "there",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "why",
        # task-description noise
        "fix",
        "bug",
        "issue",
        "error",
        "problem",
        "please",
        "need",
        "want",
        "make",
        "sure",
        "look",
        "find",
        "check",
        "update",
        "change",
        "add",
        "remove",
        "delete",
        "create",
        "new",
        "old",
        "use",
        "using",
        "used",
        "get",
        "set",
        "see",
        "try",
        "like",
        "work",
        "works",
        "working",
        "file",
        "files",
        "code",
        "line",
        "lines",
        "function",
        "method",
        "class",
        "module",
        "implement",
        "implemented",
        "following",
        "below",
        "above",
        "currently",
        "still",
        "now",
        "after",
        "before",
    }
)

# Minimum token length worth keeping.
_MIN_TOKEN_LEN = 3

# Maximum keywords returned.
_MAX_KEYWORDS = 10

# Regex that splits camelCase and PascalCase boundaries.
# "getUserById" -> ["get", "User", "By", "Id"]
_CAMEL_SPLIT_RE = re.compile(
    r"""
    (?<=[a-z])(?=[A-Z])        # aB  -> a | B
    | (?<=[A-Z])(?=[A-Z][a-z]) # ABc -> A | Bc
    | [-_./\\]                 # common path / identifier separators
    """,
    re.VERBOSE,
)

# Tokenizer: split on whitespace, punctuation (keeping internal hyphens/dots
# for qualified names like "user.service" or "pre-referral").
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]*[A-Za-z0-9]|[A-Za-z]")


def _split_camel(token: str) -> list[str]:
    """Break a camelCase or PascalCase token into its sub-words.

    Examples:
        >>> _split_camel("getUserById")
        ['get', 'user', 'by', 'id']
        >>> _split_camel("HTMLParser")
        ['html', 'parser']
    """
    parts = _CAMEL_SPLIT_RE.split(token)
    return [p.lower() for p in parts if p]


def extract_keywords(task: str) -> list[str]:
    """Extract search-worthy keywords from a free-text task description.

    The function is intentionally conservative: it prefers fewer, more
    specific keywords over a noisy bag of words.  Longer tokens are ranked
    first because they tend to be more specific identifiers (e.g.
    ``leadsListingService`` beats ``leads``).

    Args:
        task: The raw task description / issue body.

    Returns:
        A deduplicated list of keywords (lowercased), longest first, capped
        at ``_MAX_KEYWORDS`` entries.  Returns an empty list when nothing
        useful can be extracted.
    """
    if not task or not task.strip():
        return []

    raw_tokens: list[str] = _TOKEN_RE.findall(task)

    seen: set[str] = set()
    keywords: list[str] = []

    for raw in raw_tokens:
        # Keep the original compound token if it looks like a qualified name
        # (e.g. "user.service", "pre-referral", "LeadScoring").
        lowered = raw.lower()
        if lowered not in _STOP_WORDS and len(lowered) >= _MIN_TOKEN_LEN and lowered not in seen:
            seen.add(lowered)
            keywords.append(lowered)

        # Also expand camelCase / PascalCase sub-words so that
        # "getUserById" contributes both "getuserbyid" (compound) and
        # "user" (sub-word), improving recall.
        for sub in _split_camel(raw):
            if sub not in _STOP_WORDS and len(sub) >= _MIN_TOKEN_LEN and sub not in seen:
                seen.add(sub)
                keywords.append(sub)

    # Sort by descending length -- longer tokens are more specific.
    keywords.sort(key=len, reverse=True)

    return keywords[:_MAX_KEYWORDS]
