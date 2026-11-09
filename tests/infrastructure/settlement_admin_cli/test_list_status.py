from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from scripts.settlement_admin import main

from src.application.technician_settlement.list_status import (
    SettlementStatusReport,
    SettlementStatusRow,
)

from .fakes import _deps


@dataclass
class _FakeListStatus:
    report: SettlementStatusReport

    def execute(self) -> SettlementStatusReport:
        return self.report


def test_list_status_prints_settlement_status_cards(capsys: pytest.CaptureFixture[str]) -> None:
    list_status = _FakeListStatus(
        report=SettlementStatusReport(
            rows=(
                SettlementStatusRow(
                    technician_id="10001",
                    technician_label="Иванов И. (10001)",
                    warehouse_open=False,
                    unreconciled_count=3,
                    oldest_opened_at=datetime(2026, 5, 1, 5, 0, tzinfo=UTC),
                ),
                SettlementStatusRow(
                    technician_id="10004",
                    technician_label="Козлов К. (10004)",
                    warehouse_open=True,
                    unreconciled_count=0,
                    oldest_opened_at=None,
                ),
            ),
        ),
    )
    code = main(
        ["list-status"],
        deps=_deps(
            list_status=list_status,
            audit_timezone=ZoneInfo("Europe/Moscow"),
        ),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "[open_warehouses]" not in out
    assert "[unreconciled]" not in out
    expected = (
        "[settlement_status]\n"
        "\n"
        "Иванов И. (10001)\n"
        "склад: закрыт\n"
        "несверенных периодов: 3\n"
        "самый старый opened_at: 01.05.2026 08:00:00\n"
        "\n"
        "Козлов К. (10004)\n"
        "склад: открыт\n"
        "несверенных периодов: 0\n"
        "самый старый opened_at: —\n"
    )
    assert out == expected or out == expected + "\n"


def test_list_status_prints_none_when_empty(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["list-status"],
        deps=_deps(
            list_status=_FakeListStatus(report=SettlementStatusReport(rows=())),
            audit_timezone=ZoneInfo("Europe/Moscow"),
        ),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("[settlement_status]\n(none)")
