"""Parse and validate context.yaml configuration for deterministic checks.

context.yaml lives at the repo root and declares lint, test, format,
sandbox, and test_mapping settings that drive the after-agent middleware.
"""

from __future__ import annotations

from typing import Any

import yaml


_DEFAULT_CONFIG: dict[str, Any] = {
    "lint": {
        "command": "",
        "autofix": "",
    },
    "format": {
        "check": "",
    },
    "test": {
        "command": "",
        "selective": "",
        "test_dir": "test/",
    },
    "test_mapping": {
        "rules": [],
        "fallback": "test/",
    },
    "sandbox": {
        "seed": "",
        "env": {},
    },
}


def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *overrides* into a copy of *defaults*.

    Only dict values are merged recursively; scalars and lists in
    *overrides* replace the corresponding default outright.
    """
    merged: dict[str, Any] = dict(defaults)
    for key, override_value in overrides.items():
        default_value = defaults.get(key)
        if isinstance(default_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge(default_value, override_value)
        else:
            merged[key] = override_value
    return merged


def parse_context_yaml(content: str) -> dict[str, Any]:
    """Parse a YAML string into a validated configuration dict.

    Parameters
    ----------
    content:
        Raw YAML text (typically the contents of ``context.yaml``).

    Returns
    -------
    dict[str, Any]
        Configuration dict guaranteed to contain every key present in the
        default schema.  Missing or malformed input gracefully falls back
        to safe defaults (empty strings / empty collections).

    Examples
    --------
    >>> cfg = parse_context_yaml("")
    >>> cfg["test"]["test_dir"]
    'test/'
    >>> cfg = parse_context_yaml("lint:\\n  command: npm run lint")
    >>> cfg["lint"]["command"]
    'npm run lint'
    """
    if not content or not content.strip():
        return dict(_DEFAULT_CONFIG)

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError:
        return dict(_DEFAULT_CONFIG)

    if not isinstance(parsed, dict):
        return dict(_DEFAULT_CONFIG)

    return _deep_merge(_DEFAULT_CONFIG, parsed)
