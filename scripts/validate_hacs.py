#!/usr/bin/env python3
"""Fail-fast HACS package checks that also work for a private repository."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Never

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[ab]\d+)?$")
HACS_KEYS = {
    "content_in_root",
    "country",
    "filename",
    "hacs",
    "hide_default_branch",
    "homeassistant",
    "name",
    "persistent_directory",
    "render_readme",
    "zip_release",
}


def fail(message: str) -> Never:
    """Exit with a concise packaging failure."""
    raise SystemExit(f"HACS package validation failed: {message}")


def load_json(path: Path) -> dict[str, object]:
    """Load one JSON object or fail with its path."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        fail(f"{path.relative_to(ROOT)} is not valid JSON: {err}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def validate_png(path: Path) -> None:
    """Validate the required square HACS brand icon without extra packages."""
    try:
        header = path.read_bytes()[:24]
    except OSError as err:
        fail(f"cannot read {path.relative_to(ROOT)}: {err}")
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{path.relative_to(ROOT)} must be a PNG image")
    width, height = struct.unpack(">II", header[16:24])
    if width != height or width < 256:
        fail("brand/icon.png must be square and at least 256 px")


def main() -> None:
    """Validate HACS and Home Assistant manifests plus brand assets."""
    hacs = load_json(ROOT / "hacs.json")
    unknown = set(hacs) - HACS_KEYS
    if unknown:
        fail(f"unsupported hacs.json keys: {', '.join(sorted(unknown))}")
    if not isinstance(hacs.get("name"), str) or not hacs["name"]:
        fail("hacs.json requires a non-empty name")
    for key in ("homeassistant", "hacs"):
        value = hacs.get(key)
        if value is not None and (
            not isinstance(value, str) or not SEMVER.fullmatch(value)
        ):
            fail(f"hacs.json {key} must be a semantic version")
    if hacs.get("content_in_root") is True:
        fail("content_in_root must not be enabled for this integration layout")

    integrations = [
        path
        for path in (ROOT / "custom_components").iterdir()
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    if len(integrations) != 1:
        fail("custom_components must contain exactly one integration")
    integration = integrations[0]
    manifest = load_json(integration / "manifest.json")
    required = {
        "codeowners",
        "documentation",
        "domain",
        "issue_tracker",
        "name",
        "version",
    }
    missing = required - set(manifest)
    if missing:
        fail(f"manifest.json missing: {', '.join(sorted(missing))}")
    if manifest["domain"] != integration.name:
        fail("manifest domain must match its custom_components directory")
    version = manifest["version"]
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        fail("manifest version must use semantic versioning")
    expected_repo = "https://github.com/Assidefok/SCSGATE"
    if manifest["documentation"] != expected_repo:
        fail("manifest documentation URL does not match this repository")
    if manifest["issue_tracker"] != f"{expected_repo}/issues":
        fail("manifest issue tracker URL does not match this repository")

    validate_png(ROOT / "brand" / "icon.png")
    validate_png(integration / "brand" / "icon.png")
    print(f"HACS package structure valid for SCSGATE {version}")


if __name__ == "__main__":
    main()
