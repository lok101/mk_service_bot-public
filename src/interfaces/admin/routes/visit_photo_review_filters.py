from __future__ import annotations

import re
from datetime import date
from typing import Literal
from urllib.parse import urlencode

from beartype import beartype
from fastapi import Request

from src.application.visit_photo_review import ProblemRow
from src.application.visit_photo_review.ports import EDITOR_EXCLUDED_GROUP_IDS
from src.domain.visit_photo_review import CatalogGroup, ReviewCatalog
from src.interfaces.admin.deps import AdminHttpDeps

__all__ = [
    "FilterChoice",
    "FilterDefect",
    "FilterGroup",
    "Filters",
    "active_tab",
    "choice_rows",
    "content_filter_groups",
    "day_display",
    "day_iso_for_picker",
    "facet_labels",
    "filters_from_request",
    "matching_defect_code",
    "parse_day_param",
    "problem_options",
    "query_string",
]


@beartype
class FilterDefect:
    def __init__(self, *, code: str, label: str) -> None:
        self.code = code
        self.label = label


@beartype
class FilterGroup:
    def __init__(
        self,
        *,
        group_id: str,
        title: str,
        defects: tuple[FilterDefect, ...],
    ) -> None:
        self.group_id = group_id
        self.title = title
        self.defects = defects


@beartype
class FilterChoice:
    def __init__(self, *, choice_id: str, label: str) -> None:
        self.id = choice_id
        self.label = label


@beartype
def matching_defect_code(group: CatalogGroup | None, defect_query: str | None) -> str | None:
    if group is None or not defect_query:
        return None
    needle = defect_query.casefold()
    for defect in group.defects:
        if needle in {defect.code.casefold(), defect.label.casefold()}:
            return defect.code
    return None


@beartype
def content_filter_groups(catalog: ReviewCatalog) -> list[FilterGroup]:
    groups = [group for group in catalog.groups if group.group_id not in EDITOR_EXCLUDED_GROUP_IDS]
    groups.sort(key=lambda group: group.title.casefold())
    return [
        FilterGroup(
            group_id=group.group_id,
            title=group.title,
            defects=tuple(
                FilterDefect(code=defect.code, label=defect.label) for defect in group.defects
            ),
        )
        for group in groups
    ]


@beartype
def problem_options(
    groups: list[FilterGroup],
    group_id: str | None,
) -> tuple[FilterDefect, ...]:
    if not group_id:
        return ()
    for group in groups:
        if group.group_id == group_id:
            return group.defects
    return ()


@beartype
def facet_labels(
    deps: AdminHttpDeps,
    rows: tuple[ProblemRow, ...],
    *,
    key: Literal["machine_id", "technician_id"],
    label_keys: tuple[str, ...],
    selected_id: str | None,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        row_id = row.machine_id if key == "machine_id" else row.technician_id
        if not row_id:
            continue
        from src.interfaces.admin.routes.visit_photo_review_http import (
            block_labels as _block_labels,
        )

        labels = _block_labels(deps, row.machine_id, row.technician_id)
        label = ""
        for label_key in label_keys:
            candidate = labels.get(label_key, "")
            if candidate:
                label = candidate
                break
        mapping.setdefault(row_id, label or row_id)
    if selected_id and selected_id not in mapping:
        mapping[selected_id] = selected_id
    return mapping


@beartype
def choice_rows(mapping: dict[str, str]) -> tuple[FilterChoice, ...]:
    ordered = sorted(mapping.items(), key=lambda item: item[1].casefold())
    return tuple(FilterChoice(choice_id=key, label=label) for key, label in ordered)


@beartype
class Filters:
    def __init__(
        self,
        *,
        day: date | None,
        day_raw: str,
        group_id: str | None,
        machine_id: str | None,
        technician_id: str | None,
        offset: int,
        view_filter: Literal["unviewed", "all"],
        defect_query: str | None = None,
    ) -> None:
        self.day = day
        self.day_raw = day_raw
        self.group_id = group_id
        self.machine_id = machine_id
        self.technician_id = technician_id
        self.offset = offset
        self.view_filter = view_filter
        self.defect_query = defect_query


@beartype
def filters_from_request(request: Request, *, day_raw: str) -> Filters:
    day = parse_day_param(day_raw)
    group_raw = request.query_params.get("group_id", "").strip()
    machine_raw = request.query_params.get("machine_id", "").strip()
    tech_raw = request.query_params.get("technician_id", "").strip()
    defect_raw = request.query_params.get("defect", "").strip()
    if not defect_raw:
        defect_raw = request.query_params.get("problem", "").strip()
    offset_raw = request.query_params.get("offset", "0").strip()
    view_raw = request.query_params.get("view", "unviewed").strip()
    view_filter: Literal["unviewed", "all"] = "all" if view_raw == "all" else "unviewed"
    try:
        offset = max(0, int(offset_raw))
    except ValueError:
        offset = 0
    return Filters(
        day=day,
        day_raw=day_raw,
        group_id=group_raw or None,
        machine_id=machine_raw or None,
        technician_id=tech_raw or None,
        offset=offset,
        view_filter=view_filter,
        defect_query=defect_raw or None,
    )


@beartype
def query_string(filters: Filters) -> str:
    parts: dict[str, str] = {"day": filters.day_raw}
    if filters.group_id:
        parts["group_id"] = filters.group_id
    if filters.machine_id:
        parts["machine_id"] = filters.machine_id
    if filters.technician_id:
        parts["technician_id"] = filters.technician_id
    if filters.defect_query:
        parts["defect"] = filters.defect_query
    if filters.offset:
        parts["offset"] = str(filters.offset)
    if filters.view_filter != "unviewed":
        parts["view"] = filters.view_filter
    return urlencode(parts)


@beartype
def active_tab(request: Request) -> Literal["review", "problems", "groups"]:
    raw = request.query_params.get("tab", "review").strip()
    if raw == "groups":
        # Groups catalog moved to visit photo profile editor (ISS-425).
        return "review"
    if raw == "problems":
        return "problems"
    return "review"


@beartype
def parse_day_param(day_raw: str) -> date | None:
    if day_raw == "all" or day_raw == "":
        return None
    try:
        return date.fromisoformat(day_raw)
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2})", day_raw.strip())
    if match is None:
        return None
    day_n = int(match.group(1))
    month_n = int(match.group(2))
    year_n = 2000 + int(match.group(3))
    try:
        return date(year_n, month_n, day_n)
    except ValueError:
        return None


@beartype
def day_display(day_raw: str) -> str:
    parsed = parse_day_param(day_raw)
    if parsed is None:
        return ""
    return f"{parsed.day:02d}.{parsed.month:02d}.{parsed.year % 100:02d}"


@beartype
def day_iso_for_picker(day_raw: str) -> str:
    parsed = parse_day_param(day_raw)
    if parsed is None:
        return ""
    return parsed.isoformat()
