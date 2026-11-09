from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId


class TechnicianStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MachineStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class RevisionSource(StrEnum):
    GOOGLE_FORM = "google_form"
    INTERNAL_APP = "internal_app"


@beartype
@dataclass(frozen=True, slots=True)
class PrefilledFormLink:
    url: str

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("PrefilledFormLink url must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class Technician:
    id: TechnicianId
    display_name: str
    status: TechnicianStatus


@beartype
@dataclass(frozen=True, slots=True)
class VendingMachine:
    id: MachineId
    name: str
    service_weekdays: frozenset[int] = field(default_factory=frozenset)
