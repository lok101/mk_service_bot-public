from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from beartype import beartype

from src.application.service_visits.machine_no_sales_visit_policy import (
    AlwaysAllowNoSalesVisitPolicy,
    MachineNoSalesVisitPolicy,
)
from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.open_incident_result import (
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.application.service_visits.ports import (
    MachineSalesQtyBaselineLookup,
    ServiceVisitStore,
)
from src.domain.ids import MachineId

_logger = logging.getLogger(__name__)
_DEFAULT_NO_SALES_VISIT_POLICY = AlwaysAllowNoSalesVisitPolicy()


@beartype
class OpenServiceIncident:
    def __init__(
        self,
        *,
        store: ServiceVisitStore,
        baseline_lookup: MachineSalesQtyBaselineLookup,
        min_baseline_qty: Decimal = Decimal("0"),
        visit_policy: MachineNoSalesVisitPolicy = _DEFAULT_NO_SALES_VISIT_POLICY,
    ) -> None:
        self._store = store
        self._baseline_lookup = baseline_lookup
        self._min_baseline_qty = min_baseline_qty
        self._visit_policy = visit_policy

    def would_suppress_no_sales(
        self,
        *,
        machine_id: MachineId,
        report_day: date,
    ) -> bool:
        if not self._visit_policy.allows_create_visit_on_no_sales(machine_id):
            return True
        if self._min_baseline_qty <= 0:
            return False
        baseline_avg = self._baseline_lookup.baseline_avg_qty(
            machine_id=machine_id,
            as_of_day=report_day,
        )
        return baseline_avg is not None and baseline_avg < self._min_baseline_qty

    def execute(
        self,
        *,
        machine_id: MachineId,
        ops_day: date,
        source: IncidentSource,
        visit_id: str,
        now: datetime,
        report_day: date | None = None,
    ) -> OpenIncidentResult:
        if source is IncidentSource.NO_SALES:
            if not self._visit_policy.allows_create_visit_on_no_sales(machine_id):
                return OpenIncidentResult(
                    outcome=VisitForceOutcome.NOOP,
                    machine_id=machine_id,
                    visit_id=None,
                    generation=None,
                )
            if self._min_baseline_qty > 0:
                if report_day is None:
                    raise ValueError(
                        "report_day is required for NO_SALES when turnover gate is enabled"
                    )
                baseline_avg = self._baseline_lookup.baseline_avg_qty(
                    machine_id=machine_id,
                    as_of_day=report_day,
                )
                if baseline_avg is not None and baseline_avg < self._min_baseline_qty:
                    _logger.info(
                        "service_visit_turnover_gate_suppress",
                        extra={
                            "machine_id": machine_id.value,
                            "report_day": report_day.isoformat(),
                            "baseline_avg": str(baseline_avg),
                            "min_qty": str(self._min_baseline_qty),
                        },
                    )
                    return OpenIncidentResult(
                        outcome=VisitForceOutcome.NOOP,
                        machine_id=machine_id,
                        visit_id=None,
                        generation=None,
                    )

        open_visits = self._store.list_for_machine(machine_id, status=VisitStatus.OPEN)
        today_scheduled = [
            visit
            for visit in open_visits
            if visit.kind is VisitKind.SCHEDULED and visit.due_date == ops_day
        ]
        if today_scheduled:
            boosted_visit_id: str | None = None
            for slot in today_scheduled:
                if not slot.priority_boost:
                    self._store.upsert(
                        replace(slot, priority_boost=True, updated_at=now),
                    )
                    if boosted_visit_id is None:
                        boosted_visit_id = slot.visit_id
            if boosted_visit_id is not None:
                return OpenIncidentResult(
                    outcome=VisitForceOutcome.BOOSTED_SCHEDULED,
                    machine_id=machine_id,
                    visit_id=boosted_visit_id,
                    generation=now.isoformat(),
                )
            return OpenIncidentResult(
                outcome=VisitForceOutcome.NOOP,
                machine_id=machine_id,
                visit_id=today_scheduled[0].visit_id,
                generation=None,
            )
        existing = self._store.get(visit_id)
        if existing is not None and existing.status is VisitStatus.OPEN:
            return OpenIncidentResult(
                outcome=VisitForceOutcome.NOOP,
                machine_id=machine_id,
                visit_id=visit_id,
                generation=None,
            )
        if existing is not None:
            self._store.upsert(
                replace(
                    existing,
                    due_date=ops_day,
                    status=VisitStatus.OPEN,
                    closable=True,
                    priority_boost=False,
                    incident_source=source,
                    close_type=None,
                    completed_at=None,
                    completed_by_technician_id=None,
                    maintenance_event_id=None,
                    updated_at=now,
                ),
            )
            return OpenIncidentResult(
                outcome=VisitForceOutcome.REOPENED_EXTRA,
                machine_id=machine_id,
                visit_id=visit_id,
                generation=now.isoformat(),
            )
        self._store.upsert(
            ServiceVisit(
                visit_id=visit_id,
                machine_id=machine_id,
                kind=VisitKind.EXTRA_INCIDENT,
                due_date=ops_day,
                status=VisitStatus.OPEN,
                closable=True,
                priority_boost=False,
                incident_source=source,
                close_type=None,
                completed_at=None,
                completed_by_technician_id=None,
                maintenance_event_id=None,
                created_at=now,
                updated_at=now,
            ),
        )
        return OpenIncidentResult(
            outcome=VisitForceOutcome.CREATED_EXTRA,
            machine_id=machine_id,
            visit_id=visit_id,
            generation=now.isoformat(),
        )
