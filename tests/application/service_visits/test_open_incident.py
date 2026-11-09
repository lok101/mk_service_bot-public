from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.application.service_visits.qty_baseline_lookup_fakes import (
    FakeMachineSalesQtyBaselineLookup,
)

from src.application.service_visits import (
    NullMachineSalesQtyBaselineLookup,
    NullMaintenanceOnOperationalDayLookup,
    VisitForceOutcome,
)
from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.clear_offline import ClearOfflineIncident
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import IncidentSource, VisitKind, VisitStatus
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.visit_ids import (
    no_sales_incident_visit_id,
    offline_incident_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import EventId, MachineId

_MACHINE = MachineId("101")
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
_OPENED = EventId("off-1")
_TZ = ZoneInfo("UTC")
_END_HOUR = 6
_REPORT_DAY = _WED
_NS_VISIT = no_sales_incident_visit_id(_MACHINE)


def _materialize(store: InMemoryServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )


def _opener(
    store: InMemoryServiceVisitStore,
    *,
    baseline: Decimal | None = None,
    min_qty: Decimal = Decimal("10"),
    lookup: FakeMachineSalesQtyBaselineLookup | NullMachineSalesQtyBaselineLookup | None = None,
) -> OpenServiceIncident:
    if lookup is None:
        lookup = FakeMachineSalesQtyBaselineLookup(result=baseline)
    return OpenServiceIncident(
        store=store,
        baseline_lookup=lookup,
        min_baseline_qty=min_qty,
    )


def test_incident_boosts_open_scheduled_today_without_extra() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert slot is not None and slot.priority_boost is True
    assert extra is None


def test_incident_creates_extra_when_no_open_scheduled_today() -> None:
    store = InMemoryServiceVisitStore()
    _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is not None
    assert extra.kind is VisitKind.EXTRA_INCIDENT
    assert extra.closable is True
    assert extra.status is VisitStatus.OPEN


def test_offline_cleared_clears_open_extra_without_pay() -> None:
    store = InMemoryServiceVisitStore()
    _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    ClearOfflineIncident(store=store).execute(
        opened_event_id=_OPENED,
        machine_id=_MACHINE,
        now=_NOW,
    )
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is not None
    assert extra.status is VisitStatus.CLEARED
    assert extra.close_type is None


def test_offline_cleared_removes_boost_from_todays_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    ClearOfflineIncident(store=store).execute(
        opened_event_id=_OPENED,
        machine_id=_MACHINE,
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is None
    assert slot is not None and slot.priority_boost is False


def test_no_sales_high_baseline_creates_extra() -> None:
    store = InMemoryServiceVisitStore()
    _opener(store, baseline=Decimal("40")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    extra = store.get(_NS_VISIT)
    assert extra is not None
    assert extra.kind is VisitKind.EXTRA_INCIDENT


def test_no_sales_high_baseline_boosts_scheduled_today() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    _opener(store, baseline=Decimal("40")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None and slot.priority_boost is True
    assert store.get(_NS_VISIT) is None


def test_no_sales_low_baseline_suppresses_extra() -> None:
    store = InMemoryServiceVisitStore()
    _opener(store, baseline=Decimal("2")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    assert store.get(_NS_VISIT) is None
    assert store.list_for_machine(_MACHINE) == []


def test_no_sales_low_baseline_suppresses_boost() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    _opener(store, baseline=Decimal("2")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None and slot.priority_boost is False
    assert store.get(_NS_VISIT) is None


def test_offline_low_baseline_still_opens_extra() -> None:
    store = InMemoryServiceVisitStore()
    lookup = FakeMachineSalesQtyBaselineLookup(result=Decimal("2"))
    _opener(store, min_qty=Decimal("10"), lookup=lookup).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    assert store.get(offline_incident_visit_id(_OPENED)) is not None
    assert lookup.calls == []


def test_no_sales_baseline_none_opens_as_is() -> None:
    store = InMemoryServiceVisitStore()
    _opener(store, baseline=None).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    assert store.get(_NS_VISIT) is not None


def test_no_sales_min_zero_opens_even_if_low_baseline() -> None:
    store = InMemoryServiceVisitStore()
    lookup = FakeMachineSalesQtyBaselineLookup(result=Decimal("2"))
    _opener(store, min_qty=Decimal("0"), lookup=lookup).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    assert store.get(_NS_VISIT) is not None
    assert lookup.calls == []


def test_no_sales_gate_requires_report_day_when_min_positive() -> None:
    store = InMemoryServiceVisitStore()
    with pytest.raises(ValueError, match="report_day"):
        _opener(store, baseline=Decimal("40"), min_qty=Decimal("10")).execute(
            machine_id=_MACHINE,
            ops_day=_WED,
            source=IncidentSource.NO_SALES,
            visit_id=_NS_VISIT,
            now=_NOW,
            report_day=None,
        )


def test_open_no_sales_reopens_sticky_after_cleared() -> None:
    """edge: CLEARED sticky → повторный open → OPEN (тот же visit_id)."""
    store = InMemoryServiceVisitStore()
    opener = _opener(store, min_qty=Decimal("0"))
    opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    ClearNoSalesIncident(store=store).execute(machine_id=_MACHINE, now=_NOW)
    assert store.get(_NS_VISIT) is not None
    assert store.get(_NS_VISIT).status is VisitStatus.CLEARED
    opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    reopened = store.get(_NS_VISIT)
    assert reopened is not None
    assert reopened.status is VisitStatus.OPEN
    assert reopened.closable is True


def test_open_incident_returns_created_extra() -> None:
    """happy: нет scheduled → created_extra + generation."""
    store = InMemoryServiceVisitStore()
    result = _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    assert result.outcome is VisitForceOutcome.CREATED_EXTRA
    assert result.visit_id == offline_incident_visit_id(_OPENED)
    assert result.generation == _NOW.isoformat()


def test_open_incident_returns_reopened_extra() -> None:
    """happy: был CLEARED sticky → reopen → reopened_extra."""
    store = InMemoryServiceVisitStore()
    opener = _opener(store, min_qty=Decimal("0"))
    opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
        report_day=_REPORT_DAY,
    )
    ClearNoSalesIncident(store=store).execute(
        machine_id=_MACHINE,
        now=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
    )
    result = opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    assert result.outcome is VisitForceOutcome.REOPENED_EXTRA
    assert result.visit_id == _NS_VISIT
    assert result.generation == _NOW.isoformat()


def test_open_incident_returns_boosted_scheduled() -> None:
    """happy: open scheduled today без boost → boosted_scheduled."""
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    result = _opener(store, min_qty=Decimal("0")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    assert result.outcome is VisitForceOutcome.BOOSTED_SCHEDULED
    assert result.visit_id == scheduled_visit_id(_MACHINE, _WED)
    assert result.generation == _NOW.isoformat()


def test_open_incident_returns_noop_when_already_boosted() -> None:
    """edge: scheduled уже boosted → noop."""
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    opener = _opener(store, min_qty=Decimal("0"))
    first = opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    assert first.outcome is VisitForceOutcome.BOOSTED_SCHEDULED
    second = opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    assert second.outcome is VisitForceOutcome.NOOP
    assert second.generation is None


def test_open_incident_returns_noop_when_already_open() -> None:
    """edge: extra уже OPEN → noop."""
    store = InMemoryServiceVisitStore()
    opener = _opener(store, min_qty=Decimal("0"))
    visit_id = offline_incident_visit_id(_OPENED)
    first = opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=visit_id,
        now=_NOW,
    )
    assert first.outcome is VisitForceOutcome.CREATED_EXTRA
    second = opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=visit_id,
        now=_NOW,
    )
    assert second.outcome is VisitForceOutcome.NOOP
    assert second.generation is None


def test_open_incident_returns_noop_on_turnover_suppress() -> None:
    """error/suppress: baseline < min → noop, store без visit."""
    store = InMemoryServiceVisitStore()
    result = _opener(store, baseline=Decimal("1"), min_qty=Decimal("10")).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=_NS_VISIT,
        now=_NOW,
        report_day=_REPORT_DAY,
    )
    assert result.outcome is VisitForceOutcome.NOOP
    assert store.get(_NS_VISIT) is None
