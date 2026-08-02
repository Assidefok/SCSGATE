"""Translation catalog parity tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COMPONENT = Path(__file__).parents[1] / "custom_components" / "scsgate"


def _leaf_keys(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    result: set[str] = set()
    for key, child in value.items():
        result |= _leaf_keys(child, f"{prefix}.{key}" if prefix else key)
    return result


def test_all_translations_match_source_keys() -> None:
    source = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    expected = _leaf_keys(source)

    for path in sorted((COMPONENT / "translations").glob("*.json")):
        translated = json.loads(path.read_text(encoding="utf-8"))
        assert _leaf_keys(translated) == expected, path.name
