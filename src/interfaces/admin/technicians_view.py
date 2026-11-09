from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

from src.application.master_data import Technician, TechnicianStore

TechnicianListStatus = Literal["active", "inactive", "all"]


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianRowView:
    technician_id: str
    name: str
    is_active: bool
    status_label: str


@beartype
@dataclass(frozen=True, slots=True)
class TechniciansListView:
    rows: tuple[TechnicianRowView, ...]
    status: TechnicianListStatus


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianEditView:
    technician_id: str
    name: str
    is_active: bool


@beartype
def parse_technician_list_status(raw: str | None) -> TechnicianListStatus:
    if raw == "inactive":
        return "inactive"
    if raw == "all":
        return "all"
    return "active"


@beartype
def build_technicians_list_view(
    store: TechnicianStore,
    *,
    status: TechnicianListStatus,
) -> TechniciansListView:
    rows = tuple(
        _row_from_technician(technician)
        for technician in sorted(store.list_all(), key=lambda item: item.technician_id.value)
        if _matches_status(technician, status)
    )
    return TechniciansListView(rows=rows, status=status)


@beartype
def build_technician_edit_view(technician: Technician) -> TechnicianEditView:
    return TechnicianEditView(
        technician_id=technician.technician_id.value,
        name=technician.name,
        is_active=technician.is_active,
    )


@beartype
def _matches_status(technician: Technician, status: TechnicianListStatus) -> bool:
    if status == "all":
        return True
    if status == "active":
        return technician.is_active
    return not technician.is_active


@beartype
def _row_from_technician(technician: Technician) -> TechnicianRowView:
    return TechnicianRowView(
        technician_id=technician.technician_id.value,
        name=technician.name,
        is_active=technician.is_active,
        status_label="активен" if technician.is_active else "неактивен",
    )
