from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_journal_lib.envelope import JournalEmitError, load_catalog_names
from scripts.agent_journal_lib.keys import file_sha256
from scripts.agent_journal_lib.projection import (
    build_projection_from_events,
    rebuild_projection_for_product_job,
)
from scripts.agent_journal_lib.surface_enter import (
    SURFACE_ENTER,
    SurfaceEnterError,
    emit_surface_enter,
)
from scripts.agent_process_report_lib.home_paths import default_product_id


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def test_catalog_includes_surface_enter() -> None:
    assert SURFACE_ENTER in load_catalog_names()


def test_emit_surface_enter_happy_skill_updates_projection(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill = product / "SKILL.md"
    skill.write_text("# skill\n", encoding="utf-8")
    job_id = "job-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    event = emit_surface_enter(
        product,
        job_id=job_id,
        role="skill",
        path=skill,
        outcome="success",
        parent_span_id="parent-1",
    )

    assert event["name"] == SURFACE_ENTER
    assert event["attrs"]["role"] == "skill"
    assert event["attrs"]["content_hash"] == file_sha256(skill)
    assert event["attrs"]["path"].endswith("SKILL.md")
    assert "model_id" not in event["attrs"]
    assert event["parent_span_id"] == "parent-1"

    projection = rebuild_projection_for_product_job(product, job_id)
    assert event["attrs"]["content_hash"] in projection.get("surface_hashes", [])


def test_emit_surface_enter_edge_omits_model_id(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    entry = product / "entry.py"
    entry.write_text("x\n", encoding="utf-8")

    event = emit_surface_enter(
        product,
        job_id="job-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        role="script",
        path=entry,
        outcome="success",
    )
    assert "model_id" not in event["attrs"]


def test_emit_surface_enter_error_missing_path(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    missing = product / "nope.md"

    with pytest.raises((SurfaceEnterError, JournalEmitError, FileNotFoundError, OSError)):
        emit_surface_enter(
            product,
            job_id="job-cccccccccccccccccccccccccccccccc",
            role="skill",
            path=missing,
            outcome="success",
        )


def test_projection_merge_human_marks() -> None:
    events = [
        {
            "schema_version": 1,
            "job_id": "job-h",
            "name": SURFACE_ENTER,
            "occurred_at": "2026-11-05T00:00:00Z",
            "attrs": {
                "role": "human.permit",
                "path": "scripts/x.py",
                "content_hash": "abc",
                "permit_id": "p1",
            },
        }
    ]
    projection = build_projection_from_events(events)
    marks = projection.get("human_marks", [])
    assert any("human.permit" in str(m) for m in marks)


def test_emit_human_permit_via_store(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    common = tmp_path / "git-common"
    common.mkdir()
    job_id = "job-dddddddddddddddddddddddddddddddd"

    from scripts.agent_recovery_permit_lib.store import issue_new_permit

    permit = issue_new_permit(
        common,
        issuer="agent_worktree.remove",
        source_report_id="apr-1",
        operation="remove_unregistered_lane_residue",
        target_paths=("x",),
        job_id=job_id,
        product_root=product,
    )
    projection = rebuild_projection_for_product_job(product, job_id)
    assert any(
        isinstance(m, str) and "human.permit" in m for m in projection.get("human_marks", [])
    )
    assert permit.job_id == job_id


def test_mark_cli_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    skill = product / "SKILL.md"
    skill.write_text("# s\n", encoding="utf-8")
    monkeypatch.chdir(product)

    from scripts.agent_journal_surface_mark import main as mark_main

    code = mark_main(
        [
            "--job-id",
            "job-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "--role",
            "skill",
            "--path",
            str(skill),
        ]
    )
    assert code == 0
    projection = rebuild_projection_for_product_job(product, "job-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee")
    assert file_sha256(skill) in projection.get("surface_hashes", [])


def test_emit_spec_accept_helper(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    launcher = product / "launcher.py"
    launcher.write_text("pass\n", encoding="utf-8")
    job_id = "job-ffffffffffffffffffffffffffffffff"
    event = emit_surface_enter(
        product,
        job_id=job_id,
        role="human.spec_accept",
        path=launcher,
        outcome="success",
    )
    assert event["attrs"]["role"] == "human.spec_accept"
    projection = rebuild_projection_for_product_job(product, job_id)
    assert any("human.spec_accept" in str(m) for m in projection.get("human_marks", []))


def test_no_invent_model_id_policy() -> None:
    """Helper signature: model_id only when explicitly passed (not invented)."""
    import inspect

    from scripts.agent_journal_lib import surface_enter as mod

    sig = inspect.signature(mod.emit_surface_enter)
    assert "model_id" in sig.parameters
    assert sig.parameters["model_id"].default is None


def test_product_id_in_attrs(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    _write_kernel_ref(product, home)
    entry = product / "e.py"
    entry.write_text("e\n", encoding="utf-8")
    event = emit_surface_enter(
        product,
        job_id="job-0123456789abcdef0123456789abcdef",
        role="script",
        path=entry,
        outcome="success",
    )
    assert event["attrs"]["product_id"] == default_product_id(product)
