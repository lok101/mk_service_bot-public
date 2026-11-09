from __future__ import annotations

from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.clear_offline import ClearOfflineIncident
from src.application.service_visits.close_visit import CloseServiceVisit
from src.application.service_visits.complete_open_visit_task import CompleteOpenVisitTask
from src.application.service_visits.detach_on_loading_rollback import (
    DetachVisitTaskOnLoadingRollback,
)
from src.application.service_visits.enqueue_force_notify import EnqueueVisitForceNotify
from src.application.service_visits.ensure_open_visit_task import (
    EnsureOpenVisitTask,
    EnsureOpenVisitTaskResult,
)
from src.application.service_visits.force_notify_format import (
    format_dm_force_notify,
    format_ops_force_notify,
)
from src.application.service_visits.force_notify_ports import (
    AssignedTechnicianRef,
    AssignedTechnicianResolver,
    VisitForceNotifyEventPublisher,
)
from src.application.service_visits.list_projection import VisitListRow, project_visit_list
from src.application.service_visits.machine_no_sales_visit_policy import (
    AlwaysAllowNoSalesVisitPolicy,
    MachineNoSalesVisitPolicy,
)
from src.application.service_visits.materialize import (
    MachineSchedule,
    MaterializeResult,
    MaterializeScheduledVisits,
)
from src.application.service_visits.migrate_day_based_no_sales import MigrateDayBasedNoSalesVisits
from src.application.service_visits.models import (
    CloseType,
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.application.service_visits.null_maintenance_lookup import (
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.null_qty_baseline_lookup import (
    NullMachineSalesQtyBaselineLookup,
)
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.open_incident_result import (
    OpenIncidentResult,
    VisitForceOutcome,
)
from src.application.service_visits.placement_at import resolve_placement_at
from src.application.service_visits.ports import (
    LocationDisplayLookup,
    LocationDisplaySnapshot,
    MachineSalesQtyBaselineLookup,
    MachineWeekdaysLookup,
    MaintenanceOnOperationalDayLookup,
    MaintenanceOnOperationalDaySnapshot,
    PlacementAtLookup,
    PlacementAtSnapshot,
    RosterEntriesLookup,
    RosterEntrySnapshot,
    ServiceVisitStore,
    TechnicianDisplayLookup,
)
from src.application.service_visits.refresh_roster import (
    RefreshRosterResult,
    RefreshScheduledVisitsForRosterChange,
    RosterWeekdayChange,
    cancel_open_scheduled_for_machines,
)
from src.application.service_visits.sweep_offline_extras import (
    SweepOpenOfflineExtras,
    SweepResult,
)
from src.application.service_visits.visit_board import (
    BuildVisitBoardMonth,
    VisitBoardCell,
    VisitBoardIconKind,
    VisitBoardRow,
    VisitBoardTechnicianBlock,
    VisitBoardView,
)
from src.application.service_visits.visit_ids import (
    ad_hoc_visit_id,
    field_visit_id,
    is_day_based_no_sales_visit_id,
    no_sales_incident_visit_id,
    offline_incident_visit_id,
    scheduled_visit_id,
)

__all__ = [
    "AlwaysAllowNoSalesVisitPolicy",
    "AssignedTechnicianRef",
    "AssignedTechnicianResolver",
    "BuildVisitBoardMonth",
    "ClearNoSalesIncident",
    "ClearOfflineIncident",
    "CloseServiceVisit",
    "CloseType",
    "CompleteOpenVisitTask",
    "DetachVisitTaskOnLoadingRollback",
    "EnqueueVisitForceNotify",
    "EnsureOpenVisitTask",
    "EnsureOpenVisitTaskResult",
    "IncidentSource",
    "LocationDisplayLookup",
    "LocationDisplaySnapshot",
    "MachineNoSalesVisitPolicy",
    "MachineSalesQtyBaselineLookup",
    "MachineSchedule",
    "MachineWeekdaysLookup",
    "MaintenanceOnOperationalDayLookup",
    "MaintenanceOnOperationalDaySnapshot",
    "MaterializeResult",
    "MaterializeScheduledVisits",
    "MigrateDayBasedNoSalesVisits",
    "NullMachineSalesQtyBaselineLookup",
    "NullMaintenanceOnOperationalDayLookup",
    "OpenIncidentResult",
    "OpenServiceIncident",
    "PlacementAtLookup",
    "PlacementAtSnapshot",
    "RefreshRosterResult",
    "RefreshScheduledVisitsForRosterChange",
    "RosterEntriesLookup",
    "RosterEntrySnapshot",
    "RosterWeekdayChange",
    "ServiceVisit",
    "ServiceVisitStore",
    "SweepOpenOfflineExtras",
    "SweepResult",
    "TechnicianDisplayLookup",
    "VisitBoardCell",
    "VisitBoardIconKind",
    "VisitBoardRow",
    "VisitBoardTechnicianBlock",
    "VisitBoardView",
    "VisitForceNotifyEventPublisher",
    "VisitForceOutcome",
    "VisitKind",
    "VisitListRow",
    "VisitStatus",
    "VisitTaskSource",
    "ad_hoc_visit_id",
    "cancel_open_scheduled_for_machines",
    "field_visit_id",
    "format_dm_force_notify",
    "format_ops_force_notify",
    "is_day_based_no_sales_visit_id",
    "no_sales_incident_visit_id",
    "offline_incident_visit_id",
    "project_visit_list",
    "resolve_placement_at",
    "scheduled_visit_id",
]
