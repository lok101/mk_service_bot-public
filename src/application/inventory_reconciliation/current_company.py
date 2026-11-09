from __future__ import annotations

from collections.abc import Mapping, Sequence

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import MachineCompanyOccupancy


@beartype
def open_company_id(intervals: Sequence[MachineCompanyOccupancy]) -> int | None:
    opens = [item for item in intervals if item.valid_to is None]
    if not opens:
        return None
    return max(opens, key=lambda item: item.valid_from).company_id


@beartype
def resolve_current_company_name(
    intervals: Sequence[MachineCompanyOccupancy],
    names_by_company_id: Mapping[int, str],
) -> str:
    company_id = open_company_id(intervals)
    if company_id is None:
        return ""
    return (names_by_company_id.get(company_id) or "").strip()
