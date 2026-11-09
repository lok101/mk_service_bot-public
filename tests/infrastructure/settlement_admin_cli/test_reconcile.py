from __future__ import annotations

import argparse

import pytest
from scripts.settlement_admin import main
from scripts.settlement_admin_lib.cmds.reconcile import run_reconcile_finalize
from scripts.settlement_admin_lib.parser import build_parser

from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore

from .fakes import (
    _build_finalize,
    _deps,
    _draft,
    _finalize_args,
    _inventory_finalize_result,
    _preview_args,
    _RecordingFinalize,
    _RecordingPreview,
    _RecordingWarehouseDeltaPort,
    _regular_preview,
)


def test_reconcile_preview_prints_warehouse_neutral_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview = _RecordingPreview(preview=_regular_preview())
    code = main(_preview_args(), deps=_deps(preview=preview))
    output = capsys.readouterr().out
    assert code == 0
    assert "session_cutoff:" in output
    assert "warehouse_inventory_id" in output
    assert "warehouse_delta" in output
    assert "ms_inventory_id" not in output
    assert "anchor_at:" not in output


def test_reconcile_finalize_applies_without_extra_delta_call() -> None:
    delta_port = _RecordingWarehouseDeltaPort()
    finalize = _build_finalize(delta_port=delta_port)
    calls_after_preview = delta_port.calls
    deps = _deps(finalize=finalize)
    assert main(_finalize_args(confirm=True), deps=deps) == 0
    assert delta_port.calls == calls_after_preview


def test_preview_rejects_technician_id_with_all() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["reconcile", "preview", "--technician-id", "1", "--all"])


def test_finalize_rejects_technician_id_with_all() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["reconcile", "finalize", "--technician-id", "1", "--all", "--confirm"],
        )


def test_finalize_all_with_no_drafts_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(
        command="reconcile",
        reconcile_command="finalize",
        technician_id=None,
        all=True,
        confirm=True,
    )
    code = run_reconcile_finalize(
        args,
        deps=_deps(draft_store=InMemoryReconciliationDraftStore()),
        build_deps=lambda: _deps(),
    )
    assert code == 0
    assert "drafts: (none)" in capsys.readouterr().out


def test_finalize_all_skips_audit_and_partial_fail_exits_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = InMemoryReconciliationDraftStore()
    store.upsert(_draft(technician_id="tech-ok"))  # type: ignore[arg-type]
    store.upsert(_draft(technician_id="tech-bad"))  # type: ignore[arg-type]
    finalize = _RecordingFinalize(
        result=_inventory_finalize_result(),
        fail_for=frozenset({"tech-bad"}),
    )
    code = main(
        ["reconcile", "finalize", "--all", "--confirm"],
        deps=_deps(draft_store=store, finalize=finalize),  # type: ignore[arg-type]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "blocked:" in out
    assert {call.value for call in finalize.calls} == {"tech-ok", "tech-bad"}
