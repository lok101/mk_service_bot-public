from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import BatchId, MachineId, TechnicianId
from src.domain.machine_operations.events import (
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.models import VendingMachine
from src.domain.photo_batch import PhotoRef
from src.domain.results import (
    LoadingFormPrepared,
    LoadingNotAllowed,
    LoadingPhotosAlreadySubmittedToday,
    LoadingPhotosInsufficientCount,
    LoadingPhotosNotAllowed,
    MaintenanceAlreadyCompletedToday,
    MaintenanceCooldownActive,
    MaintenanceNotAllowed,
    RevisionNotAllowed,
    ServiceCapabilities,
    TechnicianRevisionOutlookEntry,
)
from src.domain.system_user import BotRole


class LocationListScope(StrEnum):
    OWN = "own"
    OTHERS = "others"


@beartype
@dataclass(frozen=True, slots=True)
class ListAvailableMachinesQuery:
    role: BotRole
    technician_id: TechnicianId | None = None
    scope: LocationListScope = LocationListScope.OWN


@beartype
@dataclass(frozen=True, slots=True)
class GetServiceCapabilitiesCommand:
    technician_id: TechnicianId
    machine_id: MachineId


@beartype
@dataclass(frozen=True, slots=True)
class GetTechnicianRevisionOutlookQuery:
    technician_id: TechnicianId
    checked_at: datetime | None = None


@beartype
@dataclass(frozen=True, slots=True)
class RegisterRevisionFromFormCommand:
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime
    form_id: str
    form_token: str


type RegisterRevisionFromFormResult = RevisionCompleted | RevisionNotAllowed


@beartype
@dataclass(frozen=True, slots=True)
class CreateLoadingFormCommand:
    technician_id: TechnicianId
    machine_id: MachineId


@beartype
@dataclass(frozen=True, slots=True)
class RegisterLoadingFromFormCommand:
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime
    form_id: str
    form_token: str


type RegisterLoadingFromFormResult = LoadingSubmitted | LoadingNotAllowed


@beartype
@dataclass(frozen=True, slots=True)
class SubmitLoadingPhotosCommand:
    technician_id: TechnicianId
    machine_id: MachineId
    batch_id: BatchId
    submitted_at: datetime
    photos: tuple[PhotoRef, ...]
    min_photo_count: int


@beartype
@dataclass(frozen=True, slots=True)
class LoadingPhotosBlocked:
    technician_id: TechnicianId
    machine_id: MachineId
    reason: str


type SubmitLoadingPhotosResult = (
    PhotosSubmitted
    | LoadingPhotosNotAllowed
    | LoadingPhotosInsufficientCount
    | LoadingPhotosAlreadySubmittedToday
    | MaintenanceCooldownActive
    | LoadingPhotosBlocked
)


@beartype
@dataclass(frozen=True, slots=True)
class CompleteMaintenanceCommand:
    technician_id: TechnicianId
    machine_id: MachineId
    completed_at: datetime | None = None


type CompleteMaintenanceResult = (
    MaintenanceCompleted
    | MaintenanceAlreadyCompletedToday
    | MaintenanceNotAllowed
    | MaintenanceCooldownActive
)


@runtime_checkable
class ListAvailableMachines(Protocol):
    @beartype
    def execute(self, query: ListAvailableMachinesQuery) -> list[VendingMachine]: ...


@runtime_checkable
class GetServiceCapabilities(Protocol):
    @beartype
    def execute(
        self,
        command: GetServiceCapabilitiesCommand,
    ) -> ServiceCapabilities: ...


@runtime_checkable
class GetTechnicianRevisionOutlook(Protocol):
    @beartype
    def execute(
        self,
        query: GetTechnicianRevisionOutlookQuery,
    ) -> list[TechnicianRevisionOutlookEntry]: ...


@runtime_checkable
class RegisterRevisionFromForm(Protocol):
    @beartype
    def execute(
        self,
        command: RegisterRevisionFromFormCommand,
    ) -> RegisterRevisionFromFormResult: ...


@runtime_checkable
class CreateLoadingForm(Protocol):
    @beartype
    def execute(self, command: CreateLoadingFormCommand) -> LoadingFormPrepared: ...


@runtime_checkable
class RegisterLoadingFromForm(Protocol):
    @beartype
    def execute(
        self,
        command: RegisterLoadingFromFormCommand,
    ) -> RegisterLoadingFromFormResult: ...


@runtime_checkable
class CompleteMaintenance(Protocol):
    @beartype
    def execute(
        self,
        command: CompleteMaintenanceCommand,
    ) -> CompleteMaintenanceResult: ...


@runtime_checkable
class RegisterLoadingPhotos(Protocol):
    @beartype
    def execute(
        self,
        command: SubmitLoadingPhotosCommand,
    ) -> SubmitLoadingPhotosResult: ...
