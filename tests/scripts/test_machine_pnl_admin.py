from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested

_TECH = TechnicianId("tech-1")
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_LINE = ReconciliationLine(
    product_code="sku-1",
    actual_prev=Decimal("10"),
    actual=Decimal("7"),
    calculated=Decimal("5"),
    delta=Decimal("2"),
    loads_total=Decimal("0"),
    sales_total=Decimal("3"),
)
_SOURCE = "cli:machine_pnl_admin"


def _snapshot(
    *,
    period_id: str,
    machine_id: str,
    status: str = "complete",
    reconciled: bool = True,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId(machine_id),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(_LINE,),
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        reconciled=reconciled,
    )


@dataclass(frozen=True, slots=True)
class _FakeRepo:
    snapshots: tuple[ResponsibilityPeriodReconciliation, ...]

    def list_by_status(
        self,
        *,
        status: str,
        machine_id: MachineId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]:
        _ = machine_id
        return [s for s in self.snapshots if s.status == status]


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


def test_build_parser_parses_backfill_and_enqueue_alias() -> None:
    # happy: subcommands + --execute
    from scripts.machine_pnl_admin import build_parser

    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)

    dry = parser.parse_args(["backfill"])
    assert dry.command == "backfill"
    assert dry.execute is False

    execute_args = parser.parse_args(["backfill", "--execute"])
    assert execute_args.execute is True

    alias = parser.parse_args(["enqueue"])
    assert alias.command == "enqueue"
    assert alias.execute is False


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # error: no Mongo
    from src.config.mongodb import MongoSettings

    @dataclass(frozen=True, slots=True)
    class _FakeSettings:
        mongodb: MongoSettings

    monkeypatch.setattr(
        "scripts.machine_pnl_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )
    from scripts.machine_pnl_admin import _build_deps

    with pytest.raises(SystemExit) as exc_info:
        _build_deps()
    assert exc_info.value.code == 1


def _install_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshots: tuple[ResponsibilityPeriodReconciliation, ...],
    enabled: bool = True,
) -> _RecordingPublisher:
    from scripts.machine_pnl_admin import _CliDeps

    publisher = _RecordingPublisher()
    deps = _CliDeps(
        reconciliation_repo=_FakeRepo(snapshots),
        publisher=publisher,
        machine_pnl_enabled=enabled,
    )
    monkeypatch.setattr("scripts.machine_pnl_admin._build_deps", lambda: deps)
    return publisher


def test_backfill_dry_run_lists_reconciled_coffee_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # happy: dry-run candidates + no publish
    from scripts.machine_pnl_admin import main

    publisher = _install_deps(
        monkeypatch,
        snapshots=(
            _snapshot(period_id="p-ok", machine_id="101", reconciled=True),
            _snapshot(period_id="p-unrec", machine_id="102", reconciled=False),
            _snapshot(period_id="p-snack", machine_id="501", reconciled=True),
        ),
    )

    code = main(["backfill"])
    out = capsys.readouterr().out
    assert code == 0
    assert "p-ok" in out
    assert "candidates: 1" in out
    assert "skipped_snack: 1" in out
    assert "skipped_not_reconciled: 1" in out
    assert "enqueued:" not in out.lower() or "enqueued: 0" in out
    assert publisher.events == []


def test_backfill_dry_run_skips_snack_and_unreconciled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # edge: only skips, empty candidates
    from scripts.machine_pnl_admin import main

    publisher = _install_deps(
        monkeypatch,
        snapshots=(
            _snapshot(period_id="p-snack", machine_id="501", reconciled=True),
            _snapshot(period_id="p-unrec", machine_id="101", reconciled=False),
        ),
    )

    code = main(["backfill"])
    out = capsys.readouterr().out
    assert code == 0
    assert "candidates: 0" in out
    assert "skipped_snack: 1" in out
    assert "skipped_not_reconciled: 1" in out
    assert publisher.events == []


def test_backfill_execute_publishes_machine_pnl_event_ids(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # happy / idempotency contract: event_id + source_session_id
    from scripts.machine_pnl_admin import main

    publisher = _install_deps(
        monkeypatch,
        snapshots=(
            _snapshot(period_id="period-1", machine_id="101", reconciled=True),
            _snapshot(period_id="period-snack", machine_id="501", reconciled=True),
            _snapshot(period_id="period-unrec", machine_id="102", reconciled=False),
        ),
        enabled=True,
    )

    code = main(["backfill", "--execute"])
    out = capsys.readouterr().out
    assert code == 0
    assert "enqueued: 1" in out
    period_events = [e for e in publisher.events if isinstance(e, MachinePeriodPnlRequested)]
    month_events = [e for e in publisher.events if isinstance(e, MachineMonthPnlRequested)]
    assert len(period_events) == 1
    assert len(month_events) == 1
    event = period_events[0]
    assert event.event_id.value == "machine_pnl:period-1"
    assert event.period_id == "period-1"
    assert event.source_session_id == _SOURCE
    month = month_events[0]
    assert month.event_id.value == "machine_pnl_month:period-1"
    assert month.source_period_id == "period-1"
    assert month.machine_id == "101"


def test_backfill_execute_fails_when_machine_pnl_disabled(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # error: enabled=false → non-zero, no publish
    from scripts.machine_pnl_admin import main

    publisher = _install_deps(
        monkeypatch,
        snapshots=(_snapshot(period_id="period-1", machine_id="101", reconciled=True),),
        enabled=False,
    )

    code = main(["backfill", "--execute"])
    err = capsys.readouterr().err
    assert code != 0
    assert "MACHINE_PNL_ENABLED" in err
    assert publisher.events == []
