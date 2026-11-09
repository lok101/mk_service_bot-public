from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.machine_operations.ports import VendingMachineRepository
from src.application.reference_data import ReferenceDataProvider
from src.application.service_visits import AssignedTechnicianRef, TechnicianDisplayLookup
from src.application.sheets.technician_locations import find_technician_id_for_machine_in_snapshot
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class VendingMachineAssignedTechnicianResolver:
    machines: VendingMachineRepository
    telegram_users: TelegramUserResolver

    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None:
        tech_id = self.machines.find_technician_id_for_machine(machine_id)
        if tech_id is None:
            return None
        display = self.machines.find_technician_display_name(tech_id) or tech_id.value
        user = self.telegram_users.find_by_technician_id(tech_id)
        return AssignedTechnicianRef(
            technician_id=tech_id,
            display_name=display,
            telegram_user_id=user.telegram_user_id if user is not None else None,
        )


@beartype
@dataclass(frozen=True, slots=True)
class ReferenceDataAssignedTechnicianResolver:
    provider: ReferenceDataProvider
    telegram_users: TelegramUserResolver
    display: TechnicianDisplayLookup

    def resolve(self, machine_id: MachineId) -> AssignedTechnicianRef | None:
        snapshot = self.provider.coffee_locations()
        tech_id = find_technician_id_for_machine_in_snapshot(snapshot, machine_id)
        if tech_id is None:
            return None
        display = self.display.display_name(tech_id) or tech_id.value
        user = self.telegram_users.find_by_technician_id(tech_id)
        return AssignedTechnicianRef(
            technician_id=tech_id,
            display_name=display,
            telegram_user_id=user.telegram_user_id if user is not None else None,
        )
