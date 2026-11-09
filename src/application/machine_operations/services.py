from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_operations.additional_maintenance import (
    AlwaysDenyAdditionalMaintenance,
)
from src.application.machine_operations.blocked_action_reason import (
    blocked_service_action_reason,
)
from src.application.machine_operations.executor import MachineOperationsExecutor
from src.application.machine_operations.maintenance_cooldown_check import (
    is_cooldown_blocking_new_maintenance,
    is_maintenance_cooldown_bypass_active,
)
from src.application.machine_operations.ports import (
    AdditionalMaintenanceAllowed,
    CompleteMaintenanceInventoryGate,
    LoadingFormLinkProvider,
    MachineOperationsRepository,
    MaintenanceCooldownBypassReader,
    RevisionFormLinkProvider,
    TechnicianLastMaintenanceReader,
    VendingMachineRepository,
)
from src.application.machine_operations.use_cases import (
    CompleteMaintenanceCommand,
    CompleteMaintenanceResult,
    CreateLoadingFormCommand,
    GetServiceCapabilitiesCommand,
    GetTechnicianRevisionOutlookQuery,
    ListAvailableMachinesQuery,
    LoadingPhotosBlocked,
    LocationListScope,
    RegisterLoadingFromFormCommand,
    RegisterLoadingFromFormResult,
    RegisterRevisionFromFormCommand,
    RegisterRevisionFromFormResult,
    SubmitLoadingPhotosCommand,
    SubmitLoadingPhotosResult,
)
from src.domain.ids import MachineId
from src.domain.machine_operations import (
    CompleteMaintenance,
    CompleteRevision,
    SubmitLoading,
    SubmitLoadingPhotos,
)
from src.domain.machine_operations.events import MaintenanceCompleted, PhotosSubmitted
from src.domain.models import RevisionSource, VendingMachine
from src.domain.results import (
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    LoadingFormPrepared,
    MaintenanceCooldownActive,
    MaintenanceNotAllowed,
    ServiceCapabilities,
    TechnicianRevisionOutlookEntry,
    maintenance_cooldown_reason,
)
from src.domain.system_user import BotRole

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class ListAvailableMachinesService:
    """Sheets assignment filters the location list for UX; not an authorization layer.

    Cross-tech access is governed by MachineOperations aggregate phases; see
    docs/operational-assumptions.md.
    """

    repository: VendingMachineRepository

    @beartype
    def execute(self, query: ListAvailableMachinesQuery) -> list[VendingMachine]:
        if query.role is BotRole.NONE:
            return []

        if query.role is BotRole.ADMINISTRATOR and query.technician_id is None:
            return self.repository.list_all()

        if query.technician_id is None:
            return []

        if query.scope is LocationListScope.OTHERS:
            own_ids = {
                machine.id
                for machine in self.repository.list_available_for_technician(
                    query.technician_id,
                )
            }
            machines_by_id: dict[MachineId, VendingMachine] = {}
            for machine in self.repository.list_all():
                if machine.id not in own_ids:
                    machines_by_id[machine.id] = machine
            return list(machines_by_id.values())

        return self.repository.list_available_for_technician(query.technician_id)


@beartype
@dataclass(frozen=True, slots=True)
class GetServiceCapabilitiesService:
    machine_operations: MachineOperationsRepository
    revision_form_links: RevisionFormLinkProvider
    last_maintenance_reader: TechnicianLastMaintenanceReader
    maintenance_cooldown_minutes: int
    bypass_reader: MaintenanceCooldownBypassReader | None = None
    service_calendar_timezone: ZoneInfo | None = None
    additional_maintenance: AdditionalMaintenanceAllowed = field(
        default_factory=AlwaysDenyAdditionalMaintenance,
    )
    inventory_gate: CompleteMaintenanceInventoryGate | None = None

    @beartype
    def execute(self, command: GetServiceCapabilitiesCommand) -> ServiceCapabilities:
        aggregate = self.machine_operations.get(command.machine_id)
        technician_id = command.technician_id
        checked_at = datetime.now(tz=UTC)
        revision_form_link = None
        suppress_revision = (
            self.inventory_gate is not None
            and self.inventory_gate.suppress_coffee_revision(command.machine_id)
        )

        phase = aggregate.responsibility_phase(technician_id, checked_at=checked_at)
        if not suppress_revision and phase == "awaiting_handover":
            revision_form_link = self.revision_form_links.create_link(
                technician_id=technician_id,
                machine_id=command.machine_id,
            )

        bypass_active = is_maintenance_cooldown_bypass_active(
            checked_at=checked_at,
            bypass_reader=self.bypass_reader,
            service_calendar_timezone=self.service_calendar_timezone,
        )
        skip = bypass_active and phase == "awaiting_handover"
        allow = self.additional_maintenance.allows(command.machine_id, checked_at)

        caps = aggregate.get_service_capabilities(
            technician_id,
            revision_form_link=revision_form_link,
            checked_at=checked_at,
            skip_responsibility_check=skip,
            allow_additional_maintenance=allow,
            allow_missing_revision_form=suppress_revision,
        )
        if suppress_revision:
            caps = replace(
                caps,
                can_complete_revision=False,
                can_submit_loading=False,
                revision_form_link=None,
            )

        complete_reason: str | None = None
        photos_reason: str | None = None
        if self.inventory_gate is not None:
            inventory_reason = self.inventory_gate.complete_maintenance_block_reason(
                command.machine_id,
                checked_at,
            )
            photos_order_reason = self.inventory_gate.loading_photos_block_reason(
                command.machine_id,
                checked_at,
            )
            if inventory_reason is not None:
                caps = replace(
                    caps,
                    can_complete_maintenance=False,
                    can_submit_loading_photos=False,
                )
                complete_reason = inventory_reason
                photos_reason = inventory_reason
            elif photos_order_reason is not None:
                caps = replace(caps, can_submit_loading_photos=False)
                photos_reason = photos_order_reason

        cooldown_active = is_cooldown_blocking_new_maintenance(
            technician_id=technician_id,
            machine_id=command.machine_id,
            checked_at=checked_at,
            last_maintenance_reader=self.last_maintenance_reader,
            cooldown_minutes=self.maintenance_cooldown_minutes,
            bypass_reader=self.bypass_reader,
            service_calendar_timezone=self.service_calendar_timezone,
        )
        apply_pause = cooldown_active and (
            caps.responsibility_phase == "responsible" or suppress_revision
        )
        if apply_pause:
            can_complete = caps.can_complete_maintenance and not cooldown_active
            can_photos = caps.can_submit_loading_photos and (
                caps.maintenance_completed_today or not cooldown_active
            )
            pause_reason = maintenance_cooldown_reason(self.maintenance_cooldown_minutes)
            if complete_reason is None and not can_complete:
                complete_reason = pause_reason
            if photos_reason is None and not can_photos:
                photos_reason = pause_reason
            caps = replace(
                caps,
                can_complete_maintenance=can_complete,
                can_submit_loading_photos=can_photos,
            )

        return replace(
            caps,
            complete_maintenance_block_reason=complete_reason,
            loading_photos_block_reason=photos_reason,
        )


@beartype
@dataclass(frozen=True, slots=True)
class GetTechnicianRevisionOutlookService:
    machine_operations: MachineOperationsRepository
    vending_machines: VendingMachineRepository

    @beartype
    def execute(
        self,
        query: GetTechnicianRevisionOutlookQuery,
    ) -> list[TechnicianRevisionOutlookEntry]:
        checked_at = query.checked_at or datetime.now(tz=UTC)
        entries: list[TechnicianRevisionOutlookEntry] = []
        for machine in self.vending_machines.list_available_for_technician(
            query.technician_id,
        ):
            aggregate = self.machine_operations.get(machine.id)
            if (
                aggregate.responsibility_phase(query.technician_id, checked_at=checked_at)
                != "responsible"
            ):
                continue
            entries.append(
                TechnicianRevisionOutlookEntry(
                    machine_id=machine.id,
                    responsibility_expires_at=aggregate.responsibility_expires_at(),
                    revision_due_status=aggregate.revision_due_status(checked_at=checked_at),
                ),
            )
        return entries


@beartype
@dataclass(frozen=True, slots=True)
class CreateLoadingFormService:
    form_links: LoadingFormLinkProvider

    @beartype
    def execute(self, command: CreateLoadingFormCommand) -> LoadingFormPrepared:
        return LoadingFormPrepared(
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            form_link=self.form_links.create_link(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
            ),
        )


@beartype
@dataclass(frozen=True, slots=True)
class RegisterRevisionFromFormService:
    executor: MachineOperationsExecutor

    @beartype
    def execute(
        self,
        command: RegisterRevisionFromFormCommand,
    ) -> RegisterRevisionFromFormResult:
        return self.executor.execute(
            command.machine_id,
            lambda aggregate: aggregate.complete_revision(
                CompleteRevision(
                    technician_id=command.technician_id,
                    completed_at=command.submitted_at,
                    source=RevisionSource.GOOGLE_FORM,
                    form_id=command.form_id,
                    form_token=command.form_token,
                ),
            ),
        )


@beartype
@dataclass(frozen=True, slots=True)
class CompleteMaintenanceService:
    executor: MachineOperationsExecutor
    last_maintenance_reader: TechnicianLastMaintenanceReader
    maintenance_cooldown_minutes: int
    bypass_reader: MaintenanceCooldownBypassReader | None = None
    service_calendar_timezone: ZoneInfo | None = None
    additional_maintenance: AdditionalMaintenanceAllowed = field(
        default_factory=AlwaysDenyAdditionalMaintenance,
    )
    inventory_gate: CompleteMaintenanceInventoryGate | None = None

    @beartype
    def execute(self, command: CompleteMaintenanceCommand) -> CompleteMaintenanceResult:
        completed_at = command.completed_at or datetime.now(tz=UTC)

        if is_cooldown_blocking_new_maintenance(
            technician_id=command.technician_id,
            machine_id=command.machine_id,
            checked_at=completed_at,
            last_maintenance_reader=self.last_maintenance_reader,
            cooldown_minutes=self.maintenance_cooldown_minutes,
            bypass_reader=self.bypass_reader,
            service_calendar_timezone=self.service_calendar_timezone,
        ):
            reason = blocked_service_action_reason(
                action="complete_maintenance",
                caps=None,
                cooldown_active=True,
                maintenance_cooldown_minutes=self.maintenance_cooldown_minutes,
                default_reason=MAINTENANCE_NOT_ALLOWED_REASON,
            )
            return MaintenanceCooldownActive(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
                reason=reason,
            )

        if self.inventory_gate is not None:
            block_reason = self.inventory_gate.complete_maintenance_block_reason(
                command.machine_id,
                completed_at,
            )
            if block_reason is not None:
                return MaintenanceNotAllowed(
                    technician_id=command.technician_id,
                    machine_id=command.machine_id,
                    reason=block_reason,
                )

        suppress_revision = (
            self.inventory_gate is not None
            and self.inventory_gate.suppress_coffee_revision(command.machine_id)
        )
        allow = self.additional_maintenance.allows(command.machine_id, completed_at)
        result = self.executor.execute(
            command.machine_id,
            lambda aggregate: aggregate.complete_maintenance(
                CompleteMaintenance(
                    technician_id=command.technician_id,
                    completed_at=completed_at,
                ),
                checked_at=completed_at,
                skip_responsibility_check=is_maintenance_cooldown_bypass_active(
                    checked_at=completed_at,
                    bypass_reader=self.bypass_reader,
                    service_calendar_timezone=self.service_calendar_timezone,
                ),
                allow_additional_maintenance=allow,
                allow_missing_revision=suppress_revision,
            ),
        )
        if (
            self.inventory_gate is not None
            and suppress_revision
            and isinstance(result, MaintenanceCompleted)
        ):
            try:
                self.inventory_gate.close_loading_order_after_visit_final(command.machine_id)
            except Exception:
                _logger.exception(
                    "micromarket_loading_close_failed",
                    extra={"machine_id": command.machine_id.value},
                )
        return result


@beartype
@dataclass(frozen=True, slots=True)
class RegisterLoadingFromFormService:
    executor: MachineOperationsExecutor

    @beartype
    def execute(
        self,
        command: RegisterLoadingFromFormCommand,
    ) -> RegisterLoadingFromFormResult:
        return self.executor.execute(
            command.machine_id,
            lambda aggregate: aggregate.submit_loading(
                SubmitLoading(
                    technician_id=command.technician_id,
                    submitted_at=command.submitted_at,
                    form_id=command.form_id,
                    form_token=command.form_token,
                ),
            ),
        )


@beartype
@dataclass(frozen=True, slots=True)
class RegisterLoadingPhotosService:
    executor: MachineOperationsExecutor
    machine_operations: MachineOperationsRepository
    last_maintenance_reader: TechnicianLastMaintenanceReader
    maintenance_cooldown_minutes: int
    bypass_reader: MaintenanceCooldownBypassReader | None = None
    service_calendar_timezone: ZoneInfo | None = None
    additional_maintenance: AdditionalMaintenanceAllowed = field(
        default_factory=AlwaysDenyAdditionalMaintenance,
    )
    inventory_gate: CompleteMaintenanceInventoryGate | None = None

    @beartype
    def execute(
        self,
        command: SubmitLoadingPhotosCommand,
    ) -> SubmitLoadingPhotosResult:
        aggregate = self.machine_operations.get(command.machine_id)
        allow = self.additional_maintenance.allows(
            command.machine_id,
            command.submitted_at,
        )
        if (
            aggregate.responsibility_phase(
                command.technician_id,
                checked_at=command.submitted_at,
            )
            == "responsible"
        ):
            caps = aggregate.get_service_capabilities(
                command.technician_id,
                revision_form_link=None,
                checked_at=command.submitted_at,
                allow_additional_maintenance=allow,
            )
            if not caps.maintenance_completed_today and is_cooldown_blocking_new_maintenance(
                technician_id=command.technician_id,
                machine_id=command.machine_id,
                checked_at=command.submitted_at,
                last_maintenance_reader=self.last_maintenance_reader,
                cooldown_minutes=self.maintenance_cooldown_minutes,
                bypass_reader=self.bypass_reader,
                service_calendar_timezone=self.service_calendar_timezone,
            ):
                reason = blocked_service_action_reason(
                    action="loading_photos",
                    caps=None,
                    cooldown_active=True,
                    maintenance_cooldown_minutes=self.maintenance_cooldown_minutes,
                    default_reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
                )
                return MaintenanceCooldownActive(
                    technician_id=command.technician_id,
                    machine_id=command.machine_id,
                    reason=reason,
                )

        suppress_revision = (
            self.inventory_gate is not None
            and self.inventory_gate.suppress_coffee_revision(command.machine_id)
        )
        if self.inventory_gate is not None:
            if suppress_revision:
                inventory_reason = self.inventory_gate.complete_maintenance_block_reason(
                    command.machine_id,
                    command.submitted_at,
                )
                if inventory_reason is not None:
                    return LoadingPhotosBlocked(
                        technician_id=command.technician_id,
                        machine_id=command.machine_id,
                        reason=inventory_reason,
                    )
            block_reason = self.inventory_gate.loading_photos_block_reason(
                command.machine_id,
                command.submitted_at,
            )
            if block_reason is not None:
                return LoadingPhotosBlocked(
                    technician_id=command.technician_id,
                    machine_id=command.machine_id,
                    reason=block_reason,
                )

        result = self.executor.execute(
            command.machine_id,
            lambda agg: agg.submit_loading_photos(
                SubmitLoadingPhotos(
                    technician_id=command.technician_id,
                    batch_id=command.batch_id,
                    submitted_at=command.submitted_at,
                    photos=command.photos,
                    min_photo_count=command.min_photo_count,
                ),
                skip_responsibility_check=is_maintenance_cooldown_bypass_active(
                    checked_at=command.submitted_at,
                    bypass_reader=self.bypass_reader,
                    service_calendar_timezone=self.service_calendar_timezone,
                ),
                allow_additional_maintenance=allow,
                allow_missing_revision=suppress_revision,
            ),
        )
        if self.inventory_gate is not None and isinstance(result, PhotosSubmitted):
            try:
                self.inventory_gate.close_loading_order_after_visit_final(command.machine_id)
            except Exception:
                _logger.exception(
                    "micromarket_loading_close_failed",
                    extra={"machine_id": command.machine_id.value},
                )
        return result
