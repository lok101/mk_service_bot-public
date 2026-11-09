from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts.agent_journal_lib.envelope import JournalEmitError, build_envelope
from scripts.agent_journal_lib.home_paths import default_job_events_path
from scripts.agent_journal_lib.keys import (
    EMITTER_JOB_LAUNCHER,
    enrich_phase_attrs,
    file_sha256,
    is_terminal_to_state,
    resolve_git_sha,
)
from scripts.agent_journal_lib.projection import (
    build_projection_from_events,
    default_job_projection_path,
    rebuild_projection,
)
from scripts.agent_journal_lib.redaction import redact_attrs
from scripts.agent_journal_lib.store import write_event
from scripts.agent_process_report_lib.home_paths import default_product_id


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")


def _git_init_with_commit(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_enrich_phase_attrs_happy_sets_product_base_emitter(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    home.mkdir()
    _write_kernel_ref(product, home)
    entry = tmp_path / "emitter.py"
    entry.write_text("print('hi')\n", encoding="utf-8")
    base_sha = "abc" * 13 + "ab"

    attrs = enrich_phase_attrs(
        {"to_state": "lane_ready", "from_state": "reserved"},
        product_root=product,
        emitter_id=EMITTER_JOB_LAUNCHER,
        emitter_path=entry,
        base_sha=base_sha,
    )

    assert attrs["product_id"] == default_product_id(product)
    assert attrs["base_sha"] == base_sha
    assert attrs["emitter_id"] == EMITTER_JOB_LAUNCHER
    assert attrs["emitter_hash"] == file_sha256(entry)
    assert "result_sha" not in attrs


def test_enrich_phase_attrs_edge_early_phase_omits_result_sha(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    home.mkdir()
    _write_kernel_ref(product, home)
    entry = tmp_path / "emitter.py"
    entry.write_text("x\n", encoding="utf-8")

    attrs = enrich_phase_attrs(
        {"to_state": "implementing"},
        product_root=product,
        emitter_id=EMITTER_JOB_LAUNCHER,
        emitter_path=entry,
        base_sha="deadbeef",
        result_sha="should-omit",
        include_result_sha=False,
    )
    assert "result_sha" not in attrs
    assert is_terminal_to_state("implementing") is False


def test_enrich_phase_attrs_sets_result_sha_on_terminal(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    home.mkdir()
    _write_kernel_ref(product, home)
    entry = tmp_path / "emitter.py"
    entry.write_text("x\n", encoding="utf-8")

    attrs = enrich_phase_attrs(
        {"to_state": "failed"},
        product_root=product,
        emitter_id=EMITTER_JOB_LAUNCHER,
        emitter_path=entry,
        base_sha="deadbeef",
        result_sha="cafebabe",
        include_result_sha=True,
    )
    assert attrs["result_sha"] == "cafebabe"
    assert is_terminal_to_state("failed") is True


def test_resolve_git_sha_once_stable(tmp_path: Path) -> None:
    sha = _git_init_with_commit(tmp_path / "repo")
    first = resolve_git_sha(tmp_path / "repo", "HEAD")
    second = resolve_git_sha(tmp_path / "repo", "HEAD")
    assert first == sha
    assert second == sha


def test_redaction_strips_forbidden_after_enrich(tmp_path: Path) -> None:
    product = tmp_path / "mk"
    home = tmp_path / "home"
    home.mkdir()
    _write_kernel_ref(product, home)
    entry = tmp_path / "emitter.py"
    entry.write_text("x\n", encoding="utf-8")
    attrs = enrich_phase_attrs(
        {"to_state": "reserved", "tool_input": "SECRET", "stdout": "leak"},
        product_root=product,
        emitter_id=EMITTER_JOB_LAUNCHER,
        emitter_path=entry,
        base_sha="aa",
    )
    cleaned = redact_attrs(attrs)
    assert "tool_input" not in cleaned
    assert "stdout" not in cleaned
    assert cleaned["emitter_id"] == EMITTER_JOB_LAUNCHER


def test_unknown_catalog_name_unchanged_error() -> None:
    with pytest.raises(JournalEmitError, match="unknown event name"):
        build_envelope(
            name="gate.unknown",
            outcome="success",
            trace_id="job-abc",
            attrs={},
        )


def test_write_event_upserts_projection(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-abc123"
    entry = tmp_path / "emitter.py"
    entry.write_text("emit\n", encoding="utf-8")
    event = build_envelope(
        name="job.phase",
        outcome="success",
        trace_id=job_id,
        job_id=job_id,
        attrs={
            "to_state": "reserved",
            "product_id": default_product_id(product),
            "base_sha": "base1",
            "emitter_id": EMITTER_JOB_LAUNCHER,
            "emitter_hash": file_sha256(entry),
        },
        event_id="evt-1",
    )
    write_event(product, job_id, event)
    proj_path = default_job_projection_path(product, job_id)
    assert proj_path.is_file()
    projection = json.loads(proj_path.read_text(encoding="utf-8"))
    assert projection["job_id"] == job_id
    assert projection["product_id"] == default_product_id(product)
    assert projection["base_sha"] == "base1"
    assert "result_sha" not in projection
    assert EMITTER_JOB_LAUNCHER in projection["emitter_ids"]


def test_rebuild_projection_matches_keys(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-deadbeef"
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={
                "to_state": "lane_ready",
                "product_id": "mk",
                "base_sha": "sha-base",
                "emitter_id": "job.launcher",
            },
            event_id="e1",
        ),
    )
    write_event(
        product,
        job_id,
        build_envelope(
            name="gate.admission",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={
                "product_id": "mk",
                "emitter_id": "doctor.admission",
                "rule": "admission",
            },
            event_id="e2",
        ),
    )
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="fail",
            trace_id=job_id,
            job_id=job_id,
            attrs={
                "to_state": "failed",
                "product_id": "mk",
                "base_sha": "sha-base",
                "result_sha": "sha-result",
                "emitter_id": "job.launcher",
            },
            event_id="e3",
        ),
    )
    events_path = default_job_events_path(product, job_id)
    proj_path = default_job_projection_path(product, job_id)
    before = json.loads(proj_path.read_text(encoding="utf-8"))
    proj_path.write_text("{not-json", encoding="utf-8")
    rebuilt = rebuild_projection(events_path)
    assert rebuilt["job_id"] == job_id
    assert rebuilt["product_id"] == "mk"
    assert rebuilt["base_sha"] == "sha-base"
    assert rebuilt["result_sha"] == "sha-result"
    assert "gate.admission" in rebuilt["gate_names"]
    assert set(rebuilt["emitter_ids"]) >= {"job.launcher", "doctor.admission"}
    assert before["base_sha"] == rebuilt["base_sha"]


def test_write_fail_leaves_projection_untouched(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    job_id = "job-cafe01"
    write_event(
        product,
        job_id,
        build_envelope(
            name="job.phase",
            outcome="success",
            trace_id=job_id,
            job_id=job_id,
            attrs={"to_state": "reserved", "product_id": "mk", "base_sha": "keep"},
            event_id="ok",
        ),
    )
    proj_path = default_job_projection_path(product, job_id)
    before = proj_path.read_text(encoding="utf-8")
    with pytest.raises(JournalEmitError):
        write_event(
            product,
            job_id,
            {
                "schema_version": 1,
                "event_id": "bad",
                "trace_id": job_id,
                "job_id": job_id,
                "name": "not.in.catalog",
                "outcome": "success",
                "occurred_at": "2026-01-01T00:00:00Z",
                "attrs": {},
            },
        )
    assert proj_path.read_text(encoding="utf-8") == before


def test_build_projection_from_events_empty() -> None:
    assert build_projection_from_events([]) == {}


def test_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"abc")
    assert file_sha256(path) == hashlib.sha256(b"abc").hexdigest()
