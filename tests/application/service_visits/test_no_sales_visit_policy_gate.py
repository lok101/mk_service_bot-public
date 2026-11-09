from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.service_visits.machine_no_sales_visit_policy import (
    AlwaysAllowNoSalesVisitPolicy,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import IncidentSource, VisitKind
from src.application.service_visits.null_qty_baseline_lookup import (
    NullMachineSalesQtyBaselineLookup,
)
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.visit_ids import no_sales_incident_visit_id
from src.domain.ids import MachineId

_MACHINE = MachineId("101")
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


class _DenyVisitPolicy:
    def allows_create_visit_on_no_sales(self, machine_id: MachineId) -> bool:
        del machine_id
        return False


def test_always_allow_policy_returns_true() -> None:
    assert AlwaysAllowNoSalesVisitPolicy().allows_create_visit_on_no_sales(
        MachineId("101"),
    )


def test_create_visit_flag_false_suppresses_extra() -> None:
    store = InMemoryServiceVisitStore()
    opener = OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
        visit_policy=_DenyVisitPolicy(),
    )
    opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=no_sales_incident_visit_id(_MACHINE),
        now=_NOW,
        report_day=_WED,
    )
    assert store.get(no_sales_incident_visit_id(_MACHINE)) is None
    assert opener.would_suppress_no_sales(machine_id=_MACHINE, report_day=_WED) is True


def test_create_visit_flag_true_opens_with_high_baseline() -> None:
    store = InMemoryServiceVisitStore()
    opener = OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
        visit_policy=AlwaysAllowNoSalesVisitPolicy(),
    )
    visit_id = no_sales_incident_visit_id(_MACHINE)
    opener.execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.NO_SALES,
        visit_id=visit_id,
        now=_NOW,
        report_day=_WED,
    )
    extra = store.get(visit_id)
    assert extra is not None
    assert extra.kind is VisitKind.EXTRA_INCIDENT
