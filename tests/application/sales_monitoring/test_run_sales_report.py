from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

import pytest

from src.application.sales_monitoring.last_maintenance import LastMaintenanceSnapshot
from src.application.sales_monitoring.run_sales_report import (
    CatalogMachine,
    EmptyCatalogError,
    RunSalesReport,
)
from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_sales import MachineSale
from src.domain.sales_monitoring.event_ids import (
    offline_cleared_event_id,
    offline_opened_event_id,
)
from src.domain.sales_monitoring.events import (
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_TZ = ZoneInfo("Asia/Yekaterinburg")
_MACHINE_A = MachineId("101")
_MACHINE_B = MachineId("102")
_TECH = TechnicianId("t-1")
_REPORT_DAY = date(2026, 7, 27)
_NOW = datetime(2026, 7, 28, 8, 0, tzinfo=_TZ)


@dataclass
class _CallLog:
    names: list[str] = field(default_factory=list)


@dataclass
class _FakePublisher:
    events: list[DomainEvent] = field(default_factory=list)

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class _FakeDrainer:
    publisher: _FakePublisher
    audit: InMemorySalesMonitoringAuditStore
    calls: list[str] = field(default_factory=list)
    _upserted_count: int = 0

    def drain_handler(self, handler_id: str) -> int:
        self.calls.append(handler_id)
        pending = self.publisher.events[self._upserted_count :]
        if not pending:
            return 0
        for event in pending:
            self.audit.upsert_from_event(event)
        drained = len(pending)
        self._upserted_count += drained
        return drained


@dataclass
class _FakeDeclineNotifier:
    texts: list[str] = field(default_factory=list)
    fail: bool = False

    def send_decline_report(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("decline telegram down")
        self.texts.append(text)


@dataclass
class _FakeSalesLoader:
    sales: tuple[MachineSale, ...] = ()
    call_log: _CallLog | None = None

    def load_for_report(
        self,
        *,
        machine_ids: Sequence[MachineId],
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        del machine_ids, opened_at, closed_at
        if self.call_log is not None:
            self.call_log.names.append("sales_load")
        return self.sales


@dataclass
class _FakeLastMaintenance:
    by_machine: dict[MachineId, LastMaintenanceSnapshot] = field(default_factory=dict)

    def get(self, machine_id: MachineId) -> LastMaintenanceSnapshot | None:
        return self.by_machine.get(machine_id)


@dataclass
class _FakeDisplayLookup:
    names: dict[TechnicianId, str] = field(default_factory=dict)

    def display_name(self, technician_id: TechnicianId) -> str | None:
        return self.names.get(technician_id)


def _sale(machine_id: MachineId, source_id: str) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=machine_id,
        product_code="p",
        quantity=Decimal("1"),
        occurred_at=datetime.combine(_REPORT_DAY, time(12), tzinfo=_TZ),
        ingested_at=_NOW,
        price=None,
    )


def _entry(
    machine_id: MachineId,
    name: str,
    *,
    tech_id: TechnicianId | None = None,
    tech_display: str | None = None,
) -> CatalogMachine:
    return CatalogMachine(
        machine_id=machine_id,
        name=name,
        assigned_technician_id=tech_id,
        assigned_technician_display=tech_display,
    )


def _build(
    *,
    sales: tuple[MachineSale, ...] = (),
    last_maintenance: _FakeLastMaintenance | None = None,
    display_lookup: _FakeDisplayLookup | None = None,
    decline_notifier: _FakeDeclineNotifier | None = None,
    call_log: _CallLog | None = None,
) -> tuple[
    RunSalesReport,
    _FakePublisher,
    InMemorySalesMonitoringAuditStore,
    _FakeDeclineNotifier,
]:
    audit = InMemorySalesMonitoringAuditStore()
    publisher = _FakePublisher()
    drainer = _FakeDrainer(publisher=publisher, audit=audit)
    analytics_notifier = decline_notifier or _FakeDeclineNotifier()
    use_case = RunSalesReport(
        sales_loader=_FakeSalesLoader(sales=sales, call_log=call_log),
        last_maintenance=last_maintenance or _FakeLastMaintenance(),
        technician_display=display_lookup or _FakeDisplayLookup(),
        publisher=publisher,
        drainer=drainer,
        decline_notifier=analytics_notifier,
    )
    return use_case, publisher, audit, analytics_notifier


def _execute(
    use_case: RunSalesReport,
    catalog: Sequence[CatalogMachine],
    *,
    branch: Literal["yesterday", "today"] = "yesterday",
    excluded_codes: frozenset[str] = frozenset(),
) -> None:
    use_case.execute(
        catalog=catalog,
        excluded_codes=excluded_codes,
        report_day=_REPORT_DAY,
        branch=branch,
        now=_NOW,
        timezone=_TZ,
        days_for_average=28,
        sales_drop_percent=30,
        sales_lookback_days=28,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
        no_sales_habitual_max_nonempty=1,
    )


def test_run_sales_report_passes_baseline_settings_to_detect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_detect(**kwargs: object) -> list[object]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "src.application.sales_monitoring.run_sales_report.detect_sales_findings",
        _fake_detect,
    )
    use_case, _, _, _ = _build(sales=(), call_log=_CallLog())
    use_case.execute(
        catalog=(_entry(_MACHINE_A, "A"),),
        excluded_codes=frozenset(),
        report_day=_REPORT_DAY,
        branch="yesterday",
        now=_NOW,
        timezone=_TZ,
        days_for_average=28,
        sales_drop_percent=30,
        sales_lookback_days=28,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
        no_sales_habitual_max_nonempty=1,
    )
    assert captured["days_for_average"] == 28
    assert captured["baseline_min_points"] == 4
    assert captured["baseline_winsorize_min_points"] == 8
    assert captured["baseline_winsorize_percent"] == 10
    assert captured["sales_drop_percent"] == 30


def test_run_sales_report_passes_habitual_max_to_detect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_detect(**kwargs: object) -> list[object]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "src.application.sales_monitoring.run_sales_report.detect_sales_findings",
        _fake_detect,
    )
    use_case, _, _, _ = _build(sales=(), call_log=_CallLog())
    use_case.execute(
        catalog=(_entry(_MACHINE_A, "A"),),
        excluded_codes=frozenset(),
        report_day=_REPORT_DAY,
        branch="yesterday",
        now=_NOW,
        timezone=_TZ,
        days_for_average=28,
        sales_drop_percent=30,
        sales_lookback_days=28,
        baseline_min_points=4,
        baseline_winsorize_min_points=8,
        baseline_winsorize_percent=10,
        no_sales_habitual_max_nonempty=0,
    )
    assert captured["no_sales_habitual_max_nonempty"] == 0


def test_report_does_not_call_offline_poll() -> None:
    """happy: report path не вызывает offline port."""
    call_log = _CallLog()
    catalog = (_entry(_MACHINE_A, "A", tech_id=_TECH, tech_display="Иван"),)
    use_case, _, _, _ = _build(
        sales=(_sale(_MACHINE_A, "s1"),),
        call_log=call_log,
    )
    _execute(use_case, catalog)
    assert "offline_poll" not in call_log.names
    assert "sales_load" in call_log.names


def test_report_succeeds_without_depending_on_offline_poll() -> None:
    """error isolation: RunSalesReport без offline_poll; Kit fail на poll не нужен report."""
    catalog = (_entry(_MACHINE_A, "A"),)
    use_case, publisher, audit, _ = _build()
    assert not hasattr(use_case, "offline_poll")
    _execute(use_case, catalog, branch="today")
    assert any(isinstance(e, SalesMonitoringTodayNoSales) for e in publisher.events)
    assert any(doc.get("kind") == "sales" for doc in audit._documents.values())


def test_report_text_omits_offline_even_when_open_in_audit() -> None:
    """Offline poll/audit остаются; report path не публикует offline-события."""
    catalog = (
        _entry(_MACHINE_A, "Open Loc"),
        _entry(_MACHINE_B, "Cleared Loc"),
    )
    use_case, publisher, audit, _ = _build(
        sales=(_sale(_MACHINE_A, "s-a"), _sale(_MACHINE_B, "s-b")),
    )
    opened_at = _NOW - timedelta(hours=2)
    opened = SalesMonitoringOfflineOpened(
        event_id=offline_opened_event_id(machine_id=_MACHINE_B, opened_at=opened_at),
        machine_id=_MACHINE_B,
        opened_at=opened_at,
        occurred_at=opened_at,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    cleared_at = _NOW - timedelta(hours=1)
    cleared = SalesMonitoringOfflineCleared(
        event_id=offline_cleared_event_id(machine_id=_MACHINE_B, cleared_at=cleared_at),
        machine_id=_MACHINE_B,
        opened_event_id=opened.event_id,
        opened_at=opened_at,
        cleared_at=cleared_at,
        occurred_at=cleared_at,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    audit.upsert_from_event(opened)
    audit.upsert_from_event(cleared)

    _execute(use_case, catalog, branch="today")
    assert not any(
        isinstance(event, (SalesMonitoringOfflineOpened, SalesMonitoringOfflineCleared))
        for event in publisher.events
    )


def test_report_enriches_audit_snapshots_assigned_and_last_serviced() -> None:
    last_at = datetime(2026, 7, 20, 12, 0, tzinfo=_TZ)
    catalog = (_entry(_MACHINE_A, "A", tech_id=_TECH, tech_display="Иван"),)
    use_case, publisher, audit, _ = _build(
        last_maintenance=_FakeLastMaintenance(
            by_machine={
                _MACHINE_A: LastMaintenanceSnapshot(
                    technician_id=TechnicianId("t-last"),
                    completed_at=last_at,
                ),
            },
        ),
        display_lookup=_FakeDisplayLookup(names={TechnicianId("t-last"): "Сергей"}),
    )
    _execute(use_case, catalog, branch="today")
    finding = next(
        event for event in publisher.events if isinstance(event, SalesMonitoringTodayNoSales)
    )
    assert finding.assigned_technician_id == _TECH
    assert finding.assigned_technician_display == "Иван"
    assert finding.last_serviced_by_technician_id == TechnicianId("t-last")
    assert finding.last_serviced_by_display == "Сергей"
    assert finding.last_serviced_at == last_at
    sales_docs = [doc for doc in audit._documents.values() if doc.get("kind") == "sales"]
    assert sales_docs
    assert sales_docs[0]["assigned_technician_display"] == "Иван"
    assert sales_docs[0]["last_serviced_by_display"] == "Сергей"


def test_report_fails_without_sending_when_catalog_empty() -> None:
    use_case, _, _, decline_notifier = _build()
    with pytest.raises(EmptyCatalogError):
        _execute(use_case, ())
    assert decline_notifier.texts == []


def test_today_detect_keeps_audit_without_ops_telegram() -> None:
    """happy isolation: today detect+drain без ops Telegram; audit на месте."""
    catalog = (_entry(_MACHINE_A, "A"),)
    use_case, publisher, audit, decline_notifier = _build()
    assert not hasattr(use_case, "report_notifier")
    _execute(use_case, catalog, branch="today")
    assert decline_notifier.texts == []
    assert any(isinstance(event, SalesMonitoringTodayNoSales) for event in publisher.events)
    assert any(doc.get("kind") == "sales" for doc in audit._documents.values())


def test_run_sales_report_does_not_send_ops() -> None:
    """happy: ops notifier не вызывается (ни yesterday, ни today)."""
    decline_notifier = _FakeDeclineNotifier()
    use_case, _, _, _ = _build(decline_notifier=decline_notifier)
    assert not hasattr(use_case, "report_notifier")
    _execute(use_case, (_entry(_MACHINE_A, "A"),), branch="yesterday")
    assert len(decline_notifier.texts) == 1
    _execute(use_case, (_entry(_MACHINE_A, "A"),), branch="today")
    assert len(decline_notifier.texts) == 1


def test_run_sales_report_yesterday_sends_empty_decline_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.application.sales_monitoring.run_sales_report.detect_sales_findings",
        lambda **kwargs: [],
    )
    decline_notifier = _FakeDeclineNotifier()
    use_case, _, _, _ = _build(decline_notifier=decline_notifier)
    _execute(use_case, (_entry(_MACHINE_A, "A"),), branch="yesterday")
    assert decline_notifier.texts == [
        f"Падение продаж за вчера ({_REPORT_DAY.isoformat()})\n\nПадений нет"
    ]


def test_run_sales_report_today_sends_ops_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.application.sales_monitoring.run_sales_report.detect_sales_findings",
        lambda **kwargs: [],
    )
    decline_notifier = _FakeDeclineNotifier()
    use_case, _, _, _ = _build(decline_notifier=decline_notifier)
    _execute(use_case, (_entry(_MACHINE_A, "A"),), branch="today")
    assert decline_notifier.texts == []


def test_run_sales_report_decline_send_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.application.sales_monitoring.run_sales_report.detect_sales_findings",
        lambda **kwargs: [],
    )
    use_case, _, _, _ = _build(decline_notifier=_FakeDeclineNotifier(fail=True))
    with pytest.raises(RuntimeError, match="decline telegram down"):
        _execute(use_case, (_entry(_MACHINE_A, "A"),), branch="yesterday")
