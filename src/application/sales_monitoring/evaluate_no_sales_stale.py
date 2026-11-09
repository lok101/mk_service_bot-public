from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from beartype import beartype

from src.application.machine_operations.ports import MaintenanceCooldownBypassReader
from src.application.sales_monitoring.no_sales_stale import (
    is_ingest_cursor_fresh,
    is_sales_stale,
)
from src.application.sales_monitoring.ports import (
    DomainEventPublisher,
    LastMaintenanceByMachine,
    MachineSalesFreshnessLookup,
    OutboxHandlerDrainer,
    SalesMonitoringAuditStore,
    TechnicianDisplayLookup,
)
from src.application.sales_monitoring.run_offline_poll import (
    SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS,
    drain_handler_until_empty,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.sales_monitoring.event_ids import (
    no_sales_stale_cleared_event_id,
    no_sales_stale_opened_event_id,
)
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
)

_LOGGER = logging.getLogger(__name__)


@beartype
def _opened_at_from_doc(document: dict[str, object]) -> datetime | None:
    value = document.get("opened_at")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return None


@beartype
def _enrich_no_sales_stale_event(
    event: SalesMonitoringNoSalesStaleOpened | SalesMonitoringNoSalesStaleCleared,
    *,
    assigned_by_machine: Mapping[MachineId, tuple[TechnicianId | None, str | None]] | None,
    last_maintenance: LastMaintenanceByMachine | None,
    technician_display: TechnicianDisplayLookup | None,
) -> SalesMonitoringNoSalesStaleOpened | SalesMonitoringNoSalesStaleCleared:
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
class EvaluateNoSalesStale:
    publisher: DomainEventPublisher
    audit_store: SalesMonitoringAuditStore
    freshness: MachineSalesFreshnessLookup
    drainer: OutboxHandlerDrainer
    bypass_reader: MaintenanceCooldownBypassReader | None = None

    def _bypass_active_at(self, *, now: datetime) -> bool:
        if self.bypass_reader is None:
            return False
        return self.bypass_reader.get_active(checked_at=now) is not None

    @beartype
    def execute(
        self,
        *,
        catalog_machine_ids: Sequence[MachineId],
        excluded_codes: frozenset[str],
        now: datetime,
        stale_hours: int,
        max_lag_minutes: int,
        last_sale_lookup_days: int,
        assigned_by_machine: (
            Mapping[MachineId, tuple[TechnicianId | None, str | None]] | None
        ) = None,
        last_maintenance: LastMaintenanceByMachine | None = None,
        technician_display: TechnicianDisplayLookup | None = None,
    ) -> None:
        # lookback applied in freshness adapter; param kept for call-site contract
        _ = last_sale_lookup_days
        active = [mid for mid in catalog_machine_ids if mid.value not in excluded_codes]

        open_by_machine: dict[MachineId, datetime] = {}
        for document in self.audit_store.list_open_no_sales():
            machine_raw = document.get("machine_id")
            if not isinstance(machine_raw, str):
                continue
            opened_at = _opened_at_from_doc(document)
            if opened_at is None:
                continue
            open_by_machine[MachineId(machine_raw)] = opened_at

        published = False
        for machine_id, open_opened_at in tuple(open_by_machine.items()):
            if machine_id.value not in excluded_codes:
                continue
            last_sale = self.freshness.last_sale_at(machine_id)
            bypass_active = self._bypass_active_at(now=now)
            cleared = SalesMonitoringNoSalesStaleCleared(
                event_id=no_sales_stale_cleared_event_id(
                    machine_id=machine_id,
                    cleared_at=now,
                ),
                machine_id=machine_id,
                opened_event_id=no_sales_stale_opened_event_id(
                    machine_id=machine_id,
                    opened_at=open_opened_at,
                ),
                opened_at=open_opened_at,
                cleared_at=now,
                occurred_at=now,
                last_sale_at=last_sale,
                assigned_technician_id=None,
                assigned_technician_display=None,
                last_serviced_by_technician_id=None,
                last_serviced_by_display=None,
                last_serviced_at=None,
                clear_trigger="exclude",
                bypass_active=bypass_active,
            )
            self.publisher.publish(
                _enrich_no_sales_stale_event(
                    cleared,
                    assigned_by_machine=assigned_by_machine,
                    last_maintenance=last_maintenance,
                    technician_display=technician_display,
                )
            )
            published = True
            del open_by_machine[machine_id]
            _LOGGER.info(
                "no_sales_stale_cleared",
                extra={
                    "machine_id": machine_id.value,
                    "last_sale_at": last_sale,
                    "stale_hours": stale_hours,
                    "clear_trigger": "exclude",
                    "bypass_active": bypass_active,
                },
            )

        if not active:
            if published:
                for handler_id in SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS:
                    drain_handler_until_empty(self.drainer, handler_id)
            return

        cursor = self.freshness.global_sales_cursor()
        cursor_ok = is_ingest_cursor_fresh(
            cursor,
            now=now,
            max_lag_minutes=max_lag_minutes,
        )
        if not cursor_ok:
            lag_minutes = None if cursor is None else int((now - cursor).total_seconds() // 60)
            _LOGGER.info(
                "no_sales_stale_skip_cursor_lag",
                extra={"cursor": cursor, "lag_minutes": lag_minutes},
            )

        for machine_id in active:
            last_sale = self.freshness.last_sale_at(machine_id)
            existing_opened_at = open_by_machine.get(machine_id)

            if not is_sales_stale(last_sale, now=now, stale_hours=stale_hours):
                if existing_opened_at is not None:
                    bypass_active = self._bypass_active_at(now=now)
                    cleared = SalesMonitoringNoSalesStaleCleared(
                        event_id=no_sales_stale_cleared_event_id(
                            machine_id=machine_id,
                            cleared_at=now,
                        ),
                        machine_id=machine_id,
                        opened_event_id=no_sales_stale_opened_event_id(
                            machine_id=machine_id,
                            opened_at=existing_opened_at,
                        ),
                        opened_at=existing_opened_at,
                        cleared_at=now,
                        occurred_at=now,
                        last_sale_at=last_sale,
                        assigned_technician_id=None,
                        assigned_technician_display=None,
                        last_serviced_by_technician_id=None,
                        last_serviced_by_display=None,
                        last_serviced_at=None,
                        clear_trigger="sale",
                        bypass_active=bypass_active,
                    )
                    self.publisher.publish(
                        _enrich_no_sales_stale_event(
                            cleared,
                            assigned_by_machine=assigned_by_machine,
                            last_maintenance=last_maintenance,
                            technician_display=technician_display,
                        )
                    )
                    published = True
                    _LOGGER.info(
                        "no_sales_stale_cleared",
                        extra={
                            "machine_id": machine_id.value,
                            "last_sale_at": last_sale,
                            "stale_hours": stale_hours,
                            "clear_trigger": "sale",
                            "bypass_active": bypass_active,
                        },
                    )
                continue

            if not cursor_ok:
                continue

            if existing_opened_at is not None:
                continue

            opened = SalesMonitoringNoSalesStaleOpened(
                event_id=no_sales_stale_opened_event_id(
                    machine_id=machine_id,
                    opened_at=now,
                ),
                machine_id=machine_id,
                opened_at=now,
                occurred_at=now,
                last_sale_at=last_sale,
                assigned_technician_id=None,
                assigned_technician_display=None,
                last_serviced_by_technician_id=None,
                last_serviced_by_display=None,
                last_serviced_at=None,
            )
            self.publisher.publish(
                _enrich_no_sales_stale_event(
                    opened,
                    assigned_by_machine=assigned_by_machine,
                    last_maintenance=last_maintenance,
                    technician_display=technician_display,
                )
            )
            published = True
            _LOGGER.info(
                "no_sales_stale_opened",
                extra={
                    "machine_id": machine_id.value,
                    "last_sale_at": last_sale,
                    "stale_hours": stale_hours,
                },
            )

        if published:
            for handler_id in SERVICE_MONITORING_POST_PUBLISH_DRAIN_IDS:
                drain_handler_until_empty(self.drainer, handler_id)
