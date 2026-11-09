"""Unit tests for observation remediation loop baseline/check helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_kernel_release_lib.pin import PinError, pin_kernel_ref
from scripts.agent_observation_loop_lib.baseline import (
    BaselineError,
    compare_signature_sets,
    load_baseline,
    write_baseline,
)
from scripts.agent_observation_loop_lib.expected_kernel import (
    ExpectedKernelError,
    draft_expected_kernel,
)
from scripts.agent_observation_loop_lib.journal_filter import journal_recurrence_candidates
from scripts.agent_observation_loop_lib.paths import baseline_path_for
from scripts.agent_observation_loop_lib.pin_hook import pin_with_baseline_capture


def _write_manifest(path: Path) -> None:
    body = """---
id: kernel-0.1
git_tag: kernel-0.1
git_sha: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
released_at: 2026-11-09T12:00:00Z
summary: Fixture
problems:
  - text: fixture
    evidence: [ISS-528]
surfaces_touched:
  - releases/
schema_impact: none
schema_contracts: []
migration_notes: ""
---

notes
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _product_with_home(tmp_path: Path) -> tuple[Path, Path]:
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
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return product, home


def test_baseline_round_trip_happy(tmp_path: Path) -> None:
    product = tmp_path / "product"
    product.mkdir()
    signatures = {"apr:sig-a", "ado:sig-b", "journal:fp-c"}
    path = write_baseline(
        product_root=product,
        version="kernel-0.1",
        signatures=signatures,
    )
    loaded = load_baseline(product_root=product, version="kernel-0.1")
    assert path == baseline_path_for(product, "kernel-0.1")
    assert loaded.version == "kernel-0.1"
    assert loaded.signatures == frozenset(signatures)


def test_compare_gone_remaining_new() -> None:
    baseline = {"apr:a", "ado:b", "journal:c"}
    current = {"ado:b", "journal:c", "apr:d"}
    result = compare_signature_sets(baseline=baseline, current=current)
    assert result.gone == frozenset({"apr:a"})
    assert result.remaining == frozenset({"ado:b", "journal:c"})
    assert result.new == frozenset({"apr:d"})


def test_load_missing_baseline_fails(tmp_path: Path) -> None:
    product = tmp_path / "product"
    product.mkdir()
    with pytest.raises(BaselineError, match="baseline missing"):
        load_baseline(product_root=product, version="kernel-0.1")


def test_pin_hook_captures_baseline_by_default(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    inventory = lambda: {"apr:live-1", "ado:live-2"}  # noqa: E731
    pin_with_baseline_capture(
        product_root=product,
        version="kernel-0.1",
        inventory=inventory,
    )
    loaded = load_baseline(product_root=product, version="kernel-0.1")
    assert loaded.signatures == frozenset({"apr:live-1", "ado:live-2"})
    updated = json.loads((product / "kernel_ref").read_text(encoding="utf-8"))
    assert updated["ref"] == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_pin_hook_skip_baseline_does_not_write(tmp_path: Path) -> None:
    product, _home = _product_with_home(tmp_path)
    pin_with_baseline_capture(
        product_root=product,
        version="kernel-0.1",
        inventory=lambda: {"apr:x"},
        skip_baseline=True,
    )
    assert not baseline_path_for(product, "kernel-0.1").exists()


def test_pin_missing_kernel_ref_fails(tmp_path: Path) -> None:
    product = tmp_path / "product"
    product.mkdir()
    with pytest.raises(PinError, match="kernel_ref"):
        pin_kernel_ref(product_root=product, version="kernel-0.1")


def test_journal_singleton_fail_not_candidate() -> None:
    events = [
        {"fingerprint": "fp-once", "kind": "fail", "event_id": "e1"},
    ]
    assert journal_recurrence_candidates(events) == []


def test_journal_repeated_fingerprint_is_candidate() -> None:
    events = [
        {"fingerprint": "fp-repeat", "kind": "fail", "event_id": "e1"},
        {"fingerprint": "fp-repeat", "kind": "fail", "event_id": "e2"},
        {"fingerprint": "fp-other", "kind": "fail", "event_id": "e3"},
        {"fingerprint": "ok-1", "kind": "success", "event_id": "e4"},
    ]
    assert journal_recurrence_candidates(events) == ["journal:fp-repeat"]


def test_expected_kernel_next_minor() -> None:
    assert draft_expected_kernel("kernel-0.1") == "kernel-0.2"
    assert draft_expected_kernel("kernel-1.9") == "kernel-1.10"


def test_expected_kernel_major_on_schema_break() -> None:
    assert draft_expected_kernel("kernel-0.1", schema_break=True) == "kernel-1.0"
    assert draft_expected_kernel("kernel-2.3", schema_break=True) == "kernel-3.0"


def test_expected_kernel_missing_version_fails() -> None:
    with pytest.raises(ExpectedKernelError, match="version"):
        draft_expected_kernel("")
