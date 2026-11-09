from __future__ import annotations

import pytest
from scripts.settlement_admin import main
from scripts.settlement_admin_lib.parser import build_parser

from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore

from .fakes import (
    _TECHNICIAN_ID,
    _deps,
    _draft,
    _exit_finalize_result,
    _RecordingFinalizeExit,
    _RecordingPreviewExit,
    _regular_preview,
)


def test_exit_reconcile_finalize_without_confirm_exits_error() -> None:
    with pytest.raises(SystemExit, match="--confirm"):
        main(
            ["exit-reconcile", "finalize", "--technician-id", "tech-1"],
            deps=_deps(finalize_exit=_RecordingFinalizeExit(result=_exit_finalize_result())),
        )


def test_exit_reconcile_preview_calls_preview_exit_uc(
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview_exit = _RecordingPreviewExit(preview=_regular_preview())
    code = main(
        ["exit-reconcile", "preview", "--technician-id", "tech-1"],
        deps=_deps(preview_exit=preview_exit),
    )
    assert code == 0
    assert preview_exit.calls == [_TECHNICIAN_ID]
    assert "warehouse_inventory_id" in capsys.readouterr().out


def test_exit_preview_rejects_technician_id_with_all() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["exit-reconcile", "preview", "--technician-id", "1", "--all"])


def test_exit_preview_all_skips_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    preview_exit = _RecordingPreviewExit(preview=_regular_preview())
    code = main(
        ["exit-reconcile", "preview", "--all"],
        deps=_deps(
            preview_exit=preview_exit,
            closed_warehouse_technician_ids=("tech-1", "tech-2"),
        ),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "=== technician_id=tech-1 ===" in out
    assert "=== technician_id=tech-2 ===" in out


def test_exit_reconcile_finalize_calls_finalize_exit_uc(
    capsys: pytest.CaptureFixture[str],
) -> None:
    finalize_exit = _RecordingFinalizeExit(result=_exit_finalize_result())
    code = main(
        ["exit-reconcile", "finalize", "--technician-id", "tech-1", "--confirm"],
        deps=_deps(finalize_exit=finalize_exit),
    )
    output = capsys.readouterr().out
    assert code == 0
    assert finalize_exit.calls == [_TECHNICIAN_ID]
    assert "mode=exit_warehouse_closed" in output
    assert "session=tech-1:exit:inv-1" in output


def test_exit_finalize_all_with_no_drafts_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        ["exit-reconcile", "finalize", "--all", "--confirm"],
        deps=_deps(draft_store=InMemoryReconciliationDraftStore()),
    )
    assert code == 0
    assert "drafts: (none)" in capsys.readouterr().out


def test_exit_finalize_all_skips_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = InMemoryReconciliationDraftStore()
    store.upsert(_draft(technician_id="tech-1", kind="exit"))  # type: ignore[arg-type]
    finalize_exit = _RecordingFinalizeExit(result=_exit_finalize_result())
    code = main(
        ["exit-reconcile", "finalize", "--all", "--confirm"],
        deps=_deps(draft_store=store, finalize_exit=finalize_exit),
    )
    assert code == 0
    assert "finalized session=" in capsys.readouterr().out
