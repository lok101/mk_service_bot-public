from __future__ import annotations

from src.domain.ids import MachineId, TechnicianId
from src.domain.results import (
    MaintenanceCooldownActive,
    maintenance_cooldown_reason,
)


def test_maintenance_cooldown_reason_formats_minutes() -> None:
    assert maintenance_cooldown_reason(20) == (
        "С момента обслуживания на другой локации прошло менее 20 мин."
    )


def test_maintenance_cooldown_active_carries_reason() -> None:
    result = MaintenanceCooldownActive(
        technician_id=TechnicianId("tech-a"),
        machine_id=MachineId("vm-01"),
        reason=maintenance_cooldown_reason(15),
    )
    assert result.reason == ("С момента обслуживания на другой локации прошло менее 15 мин.")
