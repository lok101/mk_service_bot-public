from __future__ import annotations

from src.application.machine_operations.blocked_action_reason import (
    ServiceAction,
    blocked_service_action_reason,
)
from src.application.machine_operations.cooldown_bypass_admin import (
    ClearMaintenanceCooldownBypassService,
    DisableMaintenanceCooldownBypassForTodayService,
    GetMaintenanceCooldownBypassStatusService,
    MaintenanceCooldownBypassStatus,
)
from src.application.machine_operations.errors import (
    MACHINE_OPERATIONS_CONCURRENCY_REASON,
    MachineOperationsConcurrencyError,
)
from src.application.machine_operations.use_cases import (
    CompleteMaintenance,
    CompleteMaintenanceCommand,
    CreateLoadingForm,
    CreateLoadingFormCommand,
    GetServiceCapabilities,
    GetServiceCapabilitiesCommand,
    GetTechnicianRevisionOutlookQuery,
    ListAvailableMachines,
    ListAvailableMachinesQuery,
    LocationListScope,
    RegisterLoadingFromForm,
    RegisterLoadingFromFormCommand,
    RegisterLoadingFromFormResult,
    RegisterLoadingPhotos,
    RegisterRevisionFromForm,
    RegisterRevisionFromFormCommand,
    RegisterRevisionFromFormResult,
    SubmitLoadingPhotosCommand,
    SubmitLoadingPhotosResult,
)

__all__ = [
    "ClearMaintenanceCooldownBypassService",
    "CompleteMaintenance",
    "CompleteMaintenanceCommand",
    "CreateLoadingForm",
    "CreateLoadingFormCommand",
    "DisableMaintenanceCooldownBypassForTodayService",
    "GetMaintenanceCooldownBypassStatusService",
    "GetServiceCapabilities",
    "GetServiceCapabilitiesCommand",
    "GetTechnicianRevisionOutlookQuery",
    "ListAvailableMachines",
    "ListAvailableMachinesQuery",
    "LocationListScope",
    "MACHINE_OPERATIONS_CONCURRENCY_REASON",
    "MachineOperationsConcurrencyError",
    "MaintenanceCooldownBypassStatus",
    "RegisterLoadingFromForm",
    "RegisterLoadingFromFormCommand",
    "RegisterLoadingFromFormResult",
    "RegisterLoadingPhotos",
    "RegisterRevisionFromForm",
    "RegisterRevisionFromFormCommand",
    "RegisterRevisionFromFormResult",
    "ServiceAction",
    "SubmitLoadingPhotosCommand",
    "SubmitLoadingPhotosResult",
    "blocked_service_action_reason",
]
