"""Unit tests for kernel release validate + pin."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_kernel_release_lib.layout import ensure_releases_layout
from scripts.agent_kernel_release_lib.manifest import (
    ManifestError,
    parse_manifest,
    validate_manifest,
)
from scripts.agent_kernel_release_lib.paths import manifest_path_for, releases_dir
from scripts.agent_kernel_release_lib.pin import PinError, pin_kernel_ref


def _write_manifest(path: Path, *, schema_impact: str = "none", migration: str = "") -> None:
    body = f"""---
id: kernel-0.1
git_tag: kernel-0.1
git_sha: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
released_at: 2026-11-09T12:00:00Z
summary: Initial release discipline fixture
problems:
  - text: No named kernel releases between pins
    evidence: [ISS-528]
surfaces_touched:
  - releases/
  - scripts/agent_kernel_release_lib/
schema_impact: {schema_impact}
schema_contracts: []
migration_notes: "{migration}"
---

Human notes for kernel-0.1.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_validate_fixture_manifest_happy(tmp_path: Path) -> None:
    path = tmp_path / "releases" / "kernel-0.1.md"
    _write_manifest(path)
    manifest = validate_manifest(parse_manifest(path.read_text(encoding="utf-8")))
    assert manifest.id == "kernel-0.1"
    assert manifest.schema_impact == "none"


def test_validate_compatible_schema_impact(tmp_path: Path) -> None:
    path = tmp_path / "releases" / "kernel-0.2.md"
    _write_manifest(path, schema_impact="compatible")
    text = path.read_text(encoding="utf-8").replace("kernel-0.1", "kernel-0.2")
    path.write_text(text, encoding="utf-8")
    manifest = validate_manifest(parse_manifest(path.read_text(encoding="utf-8")))
    assert manifest.schema_impact == "compatible"


def test_breaking_without_migration_notes_fails(tmp_path: Path) -> None:
    path = tmp_path / "releases" / "kernel-1.0.md"
    _write_manifest(path, schema_impact="breaking", migration="")
    text = path.read_text(encoding="utf-8").replace("kernel-0.1", "kernel-1.0")
    text = text.replace("schema_contracts: []", "schema_contracts:\n  - journal.envelope")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError, match="migration_notes"):
        validate_manifest(parse_manifest(path.read_text(encoding="utf-8")))


def test_pin_writes_kernel_ref(tmp_path: Path) -> None:
    home = tmp_path / "home"
    releases = home / "releases"
    manifest_file = releases / "kernel-0.1.md"
    _write_manifest(manifest_file)
    product = tmp_path / "product"
    product.mkdir()
    kernel_ref = {
        "home": str(home),
        "ref": "oldsha",
        "mount": {"mode": "split", "process_skills": "cursor/skills"},
    }
    (product / "kernel_ref").write_text(
        json.dumps(kernel_ref, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    pin_kernel_ref(product_root=product, version="kernel-0.1")
    updated = json.loads((product / "kernel_ref").read_text(encoding="utf-8"))
    assert updated["ref"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    baseline = product / "agent-process" / "kernel-pin-baselines" / "kernel-0.1.json"
    assert baseline.is_file()


def test_pin_skip_baseline_does_not_write_snapshot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_manifest(home / "releases" / "kernel-0.1.md")
    product = tmp_path / "product"
    product.mkdir()
    (product / "kernel_ref").write_text(
        json.dumps(
            {
                "home": str(home),
                "ref": "oldsha",
                "mount": {"mode": "split", "process_skills": "cursor/skills"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pin_kernel_ref(product_root=product, version="kernel-0.1", skip_baseline=True)
    baseline = product / "agent-process" / "kernel-pin-baselines" / "kernel-0.1.json"
    assert not baseline.exists()


def test_pin_missing_manifest_fails(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "releases").mkdir(parents=True)
    product = tmp_path / "product"
    product.mkdir()
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "x", "mount": {}}, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(PinError, match="manifest"):
        pin_kernel_ref(product_root=product, version="kernel-9.9")


def test_pin_missing_kernel_ref_fails(tmp_path: Path) -> None:
    product = tmp_path / "product"
    product.mkdir()
    with pytest.raises(PinError, match="kernel_ref"):
        pin_kernel_ref(product_root=product, version="kernel-0.1")


def test_releases_dir_helpers(tmp_path: Path) -> None:
    assert releases_dir(tmp_path) == tmp_path / "releases"
    assert manifest_path_for(tmp_path, "kernel-0.1") == tmp_path / "releases" / "kernel-0.1.md"


def test_ensure_releases_layout_writes_template_and_fixture(tmp_path: Path) -> None:
    home = tmp_path / "home"
    created = ensure_releases_layout(
        home,
        fixture_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    assert (home / "releases" / "README.md").is_file()
    assert (home / "releases" / "TEMPLATE.md").is_file()
    fixture = home / "releases" / "kernel-0.1.md"
    assert fixture.is_file()
    assert "fixture" in created
    manifest = validate_manifest(parse_manifest(fixture.read_text(encoding="utf-8")))
    assert manifest.git_sha == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
