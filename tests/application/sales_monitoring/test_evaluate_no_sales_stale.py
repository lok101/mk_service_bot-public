from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.application.sales_monitoring.evaluate_no_sales_stale import EvaluateNoSalesStale
from src.application.sales_monitoring.run_offline_poll import (
    SALES_MONITORING_AUDIT_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
)
from src.domain.events import DomainEvent
from src.domain.ids import MachineId
from src.domain.sales_monitoring.event_ids import no_sales_stale_opened_event_id
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE_A = MachineId("101")
_MACHINE_B = MachineId("102")
_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
_STALE_HOURS = 24
_MAX_LAG_MINUTES = 45
_LOOKUP_DAYS = 28
_FRESH_CURSOR = _NOW - timedelta(minutes=10)
_LAG_CURSOR = _NOW - timedelta(minutes=60)
_STALE_LAST_SALE = _NOW - timedelta(hours=25)
_FRESH_LAST_SALE = _NOW - timedelta(hours=1)
_OPENED_AT = _NOW - timedelta(hours=2)


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
    batch_sizes: list[int] = field(default_factory=lambda: [1])

    def drain_handler(self, handler_id: str) -> int:
        self.calls.append(handler_id)
        if not self.batch_sizes:
            return 0
        drained = self.batch_sizes.pop(0)
        if drained > 0:
            for event in self.publisher.events:
                self.audit.upsert_from_event(event)
        return drained


@dataclass
class _FakeFreshness:
    last_by_machine: dict[MachineId, datetime | None] = field(default_factory=dict)
    cursor: datetime | None = None
    raise_on_read: Exception | None = None

    def last_sale_at(self, machine_id: MachineId) -> datetime | None:
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.last_by_machine.get(machine_id)

    def global_sales_cursor(self) -> datetime | None:
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return self.cursor


@dataclass
class _FakeBypassReader:
    active: bool = False
    last_checked_at: datetime | None = None

    def get_active(self, *, checked_at: datetime | None = None) -> object | None:
        self.last_checked_at = checked_at
        return object() if self.active else None


def _seed_open(
    audit: InMemorySalesMonitoringAuditStore,
    *,
    machine_id: MachineId = _MACHINE_A,
    opened_at: datetime = _OPENED_AT,
    last_sale_at: datetime | None = _STALE_LAST_SALE,
) -> None:
    audit.upsert_from_event(
        SalesMonitoringNoSalesStaleOpened(
            event_id=no_sales_stale_opened_event_id(
                machine_id=machine_id,
                opened_at=opened_at,
            ),
            machine_id=machine_id,
            opened_at=opened_at,
            occurred_at=opened_at,
            last_sale_at=last_sale_at,
            assigned_technician_id=None,
            assigned_technician_display=None,
            last_serviced_by_technician_id=None,
            last_serviced_by_display=None,
            last_serviced_at=None,
        )
    )


def _build(
    *,
    freshness: _FakeFreshness,
    audit: InMemorySalesMonitoringAuditStore | None = None,
    bypass_reader: object | None = None,
) -> tuple[
    EvaluateNoSalesStale,
    _FakePublisher,
    InMemorySalesMonitoringAuditStore,
    _FakeDrainer,
]:
    publisher = _FakePublisher()
    audit_store = audit if audit is not None else InMemorySalesMonitoringAuditStore()
    drainer = _FakeDrainer(publisher=publisher, audit=audit_store)
    use_case = EvaluateNoSalesStale(
        publisher=publisher,
        audit_store=audit_store,
        freshness=freshness,
        drainer=drainer,
        bypass_reader=bypass_reader,
    )
    return use_case, publisher, audit_store, drainer


def _execute(
    use_case: EvaluateNoSalesStale,
    *,
    catalog: Sequence[MachineId] = (_MACHINE_A,),
    excluded: frozenset[str] = frozenset(),
) -> None:
    use_case.execute(
        catalog_machine_ids=catalog,
        excluded_codes=excluded,
        now=_NOW,
        stale_hours=_STALE_HOURS,
        max_lag_minutes=_MAX_LAG_MINUTES,
        last_sale_lookup_days=_LOOKUP_DAYS,
    )


def test_eval_opens_stale_when_cursor_fresh() -> None:
    """happy: stale + fresh cursor → NoSalesStaleOpened + drain."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, audit, drainer = _build(freshness=freshness)

    _execute(use_case)

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleOpened)
    assert event.machine_id == _MACHINE_A
    assert event.opened_at == _NOW
    assert event.last_sale_at == _STALE_LAST_SALE
    assert drainer.calls == [
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SALES_MONITORING_AUDIT_HANDLER_ID,
        SERVICE_VISIT_INCIDENT_HANDLER_ID,
    ]
    open_docs = audit.list_open_no_sales()
    assert len(open_docs) == 1
    assert open_docs[0]["machine_id"] == _MACHINE_A.value


def test_eval_clears_when_last_sale_fresh() -> None:
    """happy: open incident + fresh sale → Cleared даже если cursor lag."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _FRESH_LAST_SALE},
        cursor=_LAG_CURSOR,
    )
    use_case, publisher, _, drainer = _build(freshness=freshness, audit=audit)

    _execute(use_case)

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.machine_id == _MACHINE_A
    assert event.opened_at == _OPENED_AT
    assert event.opened_event_id == no_sales_stale_opened_event_id(
        machine_id=_MACHINE_A,
        opened_at=_OPENED_AT,
    )
    assert event.last_sale_at == _FRESH_LAST_SALE
    assert SALES_MONITORING_AUDIT_HANDLER_ID in drainer.calls
    assert SERVICE_VISIT_INCIDENT_HANDLER_ID in drainer.calls
    assert audit.list_open_no_sales() == []


def test_eval_skips_open_on_cursor_lag(caplog: pytest.LogCaptureFixture) -> None:
    """edge: stale но cursor lag → нет Opened; log skip."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_LAG_CURSOR,
    )
    use_case, publisher, _, drainer = _build(freshness=freshness)

    with caplog.at_level(logging.INFO):
        _execute(use_case)

    assert publisher.events == []
    assert drainer.calls == []
    assert any(record.getMessage() == "no_sales_stale_skip_cursor_lag" for record in caplog.records)


def test_eval_treats_missing_last_sale_as_stale() -> None:
    """edge: last_sale None → open при fresh cursor."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: None},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, _, _ = _build(freshness=freshness)

    _execute(use_case)

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleOpened)
    assert event.last_sale_at is None


def test_eval_excludes_machine_codes() -> None:
    """edge: excluded не публикует Opened."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE, _MACHINE_B: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, _, _ = _build(freshness=freshness)

    _execute(
        use_case,
        catalog=(_MACHINE_A, _MACHINE_B),
        excluded=frozenset({_MACHINE_A.value}),
    )

    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], SalesMonitoringNoSalesStaleOpened)
    assert publisher.events[0].machine_id == _MACHINE_B


def test_eval_clears_open_when_machine_excluded() -> None:
    """happy: open sticky + exclude → Cleared (mute), даже если last_sale ещё stale."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, audit_store, drainer = _build(freshness=freshness, audit=audit)

    _execute(use_case, excluded=frozenset({_MACHINE_A.value}))

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.machine_id == _MACHINE_A
    assert event.opened_at == _OPENED_AT
    assert event.last_sale_at == _STALE_LAST_SALE
    assert SALES_MONITORING_AUDIT_HANDLER_ID in drainer.calls
    assert SERVICE_VISIT_INCIDENT_HANDLER_ID in drainer.calls
    assert audit_store.list_open_no_sales() == []


def test_eval_excluded_without_open_publishes_nothing() -> None:
    """edge: exclude без open → нет событий."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, _, drainer = _build(freshness=freshness)

    _execute(use_case, excluded=frozenset({_MACHINE_A.value}))

    assert publisher.events == []
    assert drainer.calls == []


def test_eval_propagates_freshness_read_error() -> None:
    """error: исключение freshness → job fails (не partial silent)."""
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
        raise_on_read=RuntimeError("mongo unavailable"),
    )
    use_case, publisher, _, _ = _build(freshness=freshness)

    with pytest.raises(RuntimeError, match="mongo unavailable"):
        _execute(use_case)

    assert publisher.events == []


def test_eval_exclude_clear_sets_clear_trigger_exclude() -> None:
    """happy: машина в excluded при открытом sticky → exclude."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, _, _ = _build(freshness=freshness, audit=audit)

    _execute(use_case, excluded=frozenset({_MACHINE_A.value}))

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.clear_trigger == "exclude"
    assert event.bypass_active is False


def test_eval_fresh_sale_clear_sets_clear_trigger_sale() -> None:
    """happy: last_sale свежий при открытом sticky → sale."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _FRESH_LAST_SALE},
        cursor=_LAG_CURSOR,
    )
    use_case, publisher, _, _ = _build(freshness=freshness, audit=audit)

    _execute(use_case)

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.clear_trigger == "sale"
    assert event.bypass_active is False


def test_eval_clear_without_bypass_reader_sets_bypass_false() -> None:
    """edge: reader не передан → bypass_active is False."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _FRESH_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    use_case, publisher, _, _ = _build(freshness=freshness, audit=audit)

    _execute(use_case)

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.bypass_active is False


def test_eval_clear_with_active_bypass_sets_bypass_true() -> None:
    """happy: get_active(not None) → bypass_active True."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _FRESH_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    reader = _FakeBypassReader(active=True)
    use_case, publisher, _, _ = _build(
        freshness=freshness,
        audit=audit,
        bypass_reader=reader,
    )

    _execute(use_case)

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.bypass_active is True
    assert reader.last_checked_at == _NOW


def test_eval_clear_with_inactive_bypass_reader_sets_bypass_false() -> None:
    """edge: reader передан, get_active None → bypass_active False; checked_at=now."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _FRESH_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    reader = _FakeBypassReader(active=False)
    use_case, publisher, _, _ = _build(
        freshness=freshness,
        audit=audit,
        bypass_reader=reader,
    )

    _execute(use_case)

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.bypass_active is False
    assert reader.last_checked_at == _NOW


def test_eval_exclude_clear_with_active_bypass_sets_trigger_and_bypass() -> None:
    """happy: exclude при активном обходе → trigger exclude и bypass True."""
    audit = InMemorySalesMonitoringAuditStore()
    _seed_open(audit)
    freshness = _FakeFreshness(
        last_by_machine={_MACHINE_A: _STALE_LAST_SALE},
        cursor=_FRESH_CURSOR,
    )
    reader = _FakeBypassReader(active=True)
    use_case, publisher, _, _ = _build(
        freshness=freshness,
        audit=audit,
        bypass_reader=reader,
    )

    _execute(use_case, excluded=frozenset({_MACHINE_A.value}))

    event = publisher.events[0]
    assert isinstance(event, SalesMonitoringNoSalesStaleCleared)
    assert event.clear_trigger == "exclude"
    assert event.bypass_active is True
    assert reader.last_checked_at == _NOW
