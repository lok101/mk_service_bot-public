from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_operations import MachineOperations
from src.domain.machine_operations.events import MaintenanceCompleted
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.models import PrefilledFormLink, VendingMachine
from src.domain.technician_last_maintenance import TechnicianLastMaintenanceSnapshot


@runtime_checkable
class MachineOperationsRepository(Protocol):
    @beartype
    def get(self, machine_id: MachineId) -> MachineOperations: ...

    @beartype
    def save(self, aggregate: MachineOperations) -> None: ...


@runtime_checkable
class EventStore(Protocol):
    @beartype
    def append(self, event: DomainEvent, *, expected_version: int) -> None: ...

    @beartype
    def get_events_for_machine(self, machine_id: MachineId) -> list[DomainEvent]: ...

    @beartype
    def list_maintenance_completed_in_completed_at_window(
        self,
        machine_id: MachineId,
        *,
        completed_at_start_inclusive: datetime,
        completed_at_end_exclusive: datetime,
    ) -> tuple[MaintenanceCompleted, ...]:
        """MaintenanceCompleted for machine with completed_at in [start, end), ASC."""
        ...


@runtime_checkable
class DomainEventPublisher(Protocol):
    @beartype
    def publish(self, event: DomainEvent) -> None: ...


@runtime_checkable
class OutboxStore(Protocol):
    @beartype
    def enqueue(
        self,
        *,
        event_id: str,
        handler_id: str,
        event_document: dict[str, Any],
        not_before: datetime | None = None,
    ) -> bool: ...

    @beartype
    def claim_pending(
        self,
        *,
        limit: int,
        handler_id: str | None = None,
        handler_ids: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    @beartype
    def reclaim_stuck_processing(self) -> int: ...

    @beartype
    def mark_processed(self, entry_id: str, *, claim_id: str) -> bool: ...

    @beartype
    def mark_failed(
        self,
        entry_id: str,
        *,
        claim_id: str,
        error_message: str,
        permanent: bool = False,
        retry_delay: timedelta | None = None,
        max_attempts_override: int | None = None,
    ) -> bool: ...

    @beartype
    def find_active_portion_event_id(self, technician_id: str) -> str | None: ...


@runtime_checkable
class VendingMachineRepository(Protocol):
    @beartype
    def list_available_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[VendingMachine]: ...

    @beartype
    def list_all(self) -> list[VendingMachine]: ...

    @beartype
    def find_technician_id_for_machine(
        self,
        machine_id: MachineId,
    ) -> TechnicianId | None: ...

    @beartype
    def get(self, machine_id: MachineId) -> VendingMachine | None: ...

    @beartype
    def find_technician_display_name_for_machine(
        self,
        machine_id: MachineId,
    ) -> str | None: ...

    @beartype
    def find_technician_display_name(
        self,
        technician_id: TechnicianId,
    ) -> str | None: ...


@runtime_checkable
class RevisionFormLinkProvider(Protocol):
    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink: ...


@runtime_checkable
class LoadingFormLinkProvider(Protocol):
    @beartype
    def create_link(
        self,
        technician_id: TechnicianId,
        machine_id: MachineId,
    ) -> PrefilledFormLink: ...


class WarehouseInventoryFormUnconfigured(Exception):
    """Raised when TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL is empty (dev backup-first)."""


@runtime_checkable
class TechnicianWarehouseInventoryLinkProvider(Protocol):
    @beartype
    def create_link(self, technician_id: TechnicianId) -> PrefilledFormLink: ...


@runtime_checkable
class TechnicianLastMaintenanceReader(Protocol):
    @beartype
    def get_last(self, technician_id: TechnicianId) -> TechnicianLastMaintenanceSnapshot | None: ...


@runtime_checkable
class TechnicianLastMaintenanceProjection(Protocol):
    @beartype
    def get_last(self, technician_id: TechnicianId) -> TechnicianLastMaintenanceSnapshot | None: ...

    @beartype
    def upsert(self, snapshot: TechnicianLastMaintenanceSnapshot) -> None: ...


@runtime_checkable
class MaintenanceCooldownBypassReader(Protocol):
    @beartype
    def get_active(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> MaintenanceCooldownBypassSnapshot | None: ...


@runtime_checkable
class MaintenanceCooldownBypassStore(Protocol):
    @beartype
    def get_snapshot(self) -> MaintenanceCooldownBypassSnapshot | None: ...

    @beartype
    def upsert_for_today(
        self,
        *,
        activated_at: datetime,
        reason: str | None,
        service_calendar_timezone: ZoneInfo,
    ) -> MaintenanceCooldownBypassSnapshot: ...

    @beartype
    def clear(self) -> bool: ...


@runtime_checkable
class AdditionalMaintenanceAllowed(Protocol):
    @beartype
    def allows(self, machine_id: MachineId, at: datetime) -> bool: ...


@runtime_checkable
class CompleteMaintenanceInventoryGate(Protocol):
    """Optional kind-aware gate (micromarket inventory in operational day)."""

    @beartype
    def complete_maintenance_block_reason(
        self,
        machine_id: MachineId,
        checked_at: datetime,
    ) -> str | None: ...

    @beartype
    def suppress_coffee_revision(self, machine_id: MachineId) -> bool: ...

    @beartype
    def loading_photos_block_reason(
        self,
        machine_id: MachineId,
        checked_at: datetime,
    ) -> str | None: ...

    @beartype
    def close_loading_order_after_visit_final(self, machine_id: MachineId) -> None: ...
