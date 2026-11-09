from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from beartype import beartype

from src.application.sales_monitoring.offline_lifecycle import (
    MachineOfflineInput,
    decide_offline_lifecycle,
)
from src.application.sales_monitoring.ports import (
    DomainEventPublisher,
    KitVmStatesReader,
    LastMaintenanceByMachine,
    OutboxHandlerDrainer,
    SalesMonitoringAlertNotifier,
    SalesMonitoringAuditStore,
    TechnicianDisplayLookup,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
)

SALES_MONITORING_AUDIT_HANDLER_ID = "sales_monitoring_audit"
SERVICE_VISIT_INCIDENT_HANDLER_ID = "service_visit_incident"
SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS = (
    SALES_MONITORING_AUDIT_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
)
_DRAIN_MAX_ROUNDS = 100


@beartype
def drain_handler_until_empty(
    drainer: OutboxHandlerDrainer,
    handler_id: str,
    *,
    max_rounds: int = _DRAIN_MAX_ROUNDS,
) -> int:
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    total = 0
    for _ in range(max_rounds):
        drained = drainer.drain_handler(handler_id)
        if drained <= 0:
            return total
        total += drained
    raise RuntimeError(
        f"Outbox drain for handler {handler_id!r} did not empty after {max_rounds} rounds "
        f"(drained={total})",
    )


@beartype
def _opened_at_from_doc(document: dict[str, object]) -> datetime | None:
    value = document.get("opened_at")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return None


@beartype
def _enrich_offline_event(
    event: SalesMonitoringOfflineOpened | SalesMonitoringOfflineCleared,
    *,
    assigned_by_machine: Mapping[MachineId, tuple[TechnicianId | None, str | None]] | None,
    last_maintenance: LastMaintenanceByMachine | None,
    technician_display: TechnicianDisplayLookup | None,
) -> SalesMonitoringOfflineOpened | SalesMonitoringOfflineCleared:
    assigned_id: TechnicianId | None = None
    assigned_display: str | None = None
    if assigned_by_machine is not None:
        assigned_id, assigned_display = assigned_by_machine.get(event.machine_id, (None, None))

    last_id: TechnicianId | None = None
    last_display: str | None = None
    last_at: datetime | None = None
    if last_maintenance is not None:
        snapshot = last_maintenance.get(event.machine_id)
        if snapshot is not None:
            last_id = snapshot.technician_id
            last_at = snapshot.completed_at
            if technician_display is not None:
                last_display = technician_display.display_name(last_id)

    return replace(
        event,
        assigned_technician_id=assigned_id,
        assigned_technician_display=assigned_display,
        last_serviced_by_technician_id=last_id,
        last_serviced_by_display=last_display,
        last_serviced_at=last_at,
    )


@beartype
@dataclass(frozen=True, slots=True)
class RunOfflinePoll:
    kit_states: KitVmStatesReader
    audit_store: SalesMonitoringAuditStore
    publisher: DomainEventPublisher
    drainer: OutboxHandlerDrainer
    alert_notifier: SalesMonitoringAlertNotifier

    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: Sequence[MachineId],
        excluded_codes: frozenset[str],
        now: datetime,
        threshold_minutes: int,
        assigned_by_machine: (
            Mapping[MachineId, tuple[TechnicianId | None, str | None]] | None
        ) = None,
        last_maintenance: LastMaintenanceByMachine | None = None,
        technician_display: TechnicianDisplayLookup | None = None,
    ) -> tuple[MachineId, ...]:
        active = [mid for mid in catalog_machine_ids if mid.value not in excluded_codes]
        if not active:
            return ()

        status_by_code = {
            status.machine_code: status
            for status in self.kit_states.statuses_for(
                machine_codes=tuple(mid.value for mid in active),
                now=now,
                threshold_minutes=threshold_minutes,
            )
        }

        open_by_machine: dict[MachineId, datetime] = {}
        for document in self.audit_store.list_open_offline():
            machine_raw = document.get("machine_id")
            if not isinstance(machine_raw, str):
                continue
            opened_at = _opened_at_from_doc(document)
            if opened_at is None:
                continue
            open_by_machine[MachineId(machine_raw)] = opened_at

        inputs: list[MachineOfflineInput] = []
        for machine_id in active:
            status = status_by_code.get(machine_id.value)
            if status is None:
                inputs.append(
                    MachineOfflineInput(
                        machine_id=machine_id,
                        kit_id=None,
                        is_offline=True,
                        open_opened_at=open_by_machine.get(machine_id),
                    )
                )
                continue
            inputs.append(
                MachineOfflineInput(
                    machine_id=machine_id,
                    kit_id=status.kit_id,
                    is_offline=status.is_offline,
                    open_opened_at=open_by_machine.get(machine_id),
                )
            )

        decision = decide_offline_lifecycle(machines=inputs, now=now)

        for opened in decision.opened:
            self.publisher.publish(
                _enrich_offline_event(
                    opened,
                    assigned_by_machine=assigned_by_machine,
                    last_maintenance=last_maintenance,
                    technician_display=technician_display,
                )
            )
        for cleared in decision.cleared:
            self.publisher.publish(
                _enrich_offline_event(
                    cleared,
                    assigned_by_machine=assigned_by_machine,
                    last_maintenance=last_maintenance,
                    technician_display=technician_display,
                )
            )

        if decision.opened or decision.cleared:
            for handler_id in SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS:
                drain_handler_until_empty(self.drainer, handler_id)

        unresolved = decision.unresolved_machine_ids
        if unresolved:
            self.alert_notifier.notify_unresolved_kit_ids(
                tuple(machine_id.value for machine_id in unresolved),
            )
        return unresolved
