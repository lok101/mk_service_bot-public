from __future__ import annotations

import pytest
from scripts.settlement_admin import main

from src.application.technician_warehouse.errors import CloseTechnicianWarehouseError

from .fakes import (
    _TECHNICIAN_ID,
    _close_dry_run,
    _deps,
    _exit_closed_event,
    _RecordingCloseWarehouse,
)


def test_close_without_confirm_is_dry_run_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    close = _RecordingCloseWarehouse(dry_run=_close_dry_run())
    code = main(
        ["close-technician-warehouse", "--technician-id", "tech-1"],
        deps=_deps(close_warehouse=close),
    )
    output = capsys.readouterr().out
    assert code == 0
    assert close.calls == [(_TECHNICIAN_ID, False)]
    assert "ret-1" in output
    assert "dry-run" in output.lower() or "planned" in output.lower()


def test_close_dry_run_prints_previous_inventory_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    close = _RecordingCloseWarehouse(dry_run=_close_dry_run())
    code = main(
        ["close-technician-warehouse", "--technician-id", "tech-1"],
        deps=_deps(close_warehouse=close),
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "previous_inventory_id=synthetic_zero_baseline" in output


def test_close_confirm_calls_use_case_confirm_true(capsys: pytest.CaptureFixture[str]) -> None:
    close = _RecordingCloseWarehouse(closed=_exit_closed_event())
    code = main(
        ["close-technician-warehouse", "--technician-id", "tech-1", "--confirm"],
        deps=_deps(close_warehouse=close),
    )
    output = capsys.readouterr().out
    assert code == 0
    assert close.calls == [(_TECHNICIAN_ID, True)]
    assert "exit-1" in output


def test_close_error_exits_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    close = _RecordingCloseWarehouse(
        error=CloseTechnicianWarehouseError("last transfer must be SUPPLY_RETURN"),
    )
    code = main(
        ["close-technician-warehouse", "--technician-id", "tech-1", "--confirm"],
        deps=_deps(close_warehouse=close),
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "SUPPLY_RETURN" in err
