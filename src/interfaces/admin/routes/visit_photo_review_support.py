from __future__ import annotations

import logging
from pathlib import Path

from src.interfaces.admin.http_common import TEMPLATES
from src.interfaces.admin.routes.visit_photo_review_filters import (
    FilterChoice,
    FilterDefect,
    FilterGroup,
    Filters,
    active_tab,
    choice_rows,
    content_filter_groups,
    day_display,
    day_iso_for_picker,
    facet_labels,
    filters_from_request,
    matching_defect_code,
    parse_day_param,
    problem_options,
    query_string,
)
from src.interfaces.admin.routes.visit_photo_review_group_editor import (
    avatar_error_message,
    catalog_group_rows,
    defect_rows_from_fields,
    defects_error_message,
    find_editor_group,
    group_editor_page,
    parse_group_editor_payload,
)
from src.interfaces.admin.routes.visit_photo_review_http import (
    after_close_target,
    block_labels,
    dispose_error_response,
    json_for_script,
    mark_error_response,
    review_submit_action,
    save_error_response,
    wants_json,
)

LOGGER = logging.getLogger("src.interfaces.admin.routes.visit_photo_review")
ADMIN_DIR = Path(__file__).parent.parent
LIST_PATH = "/admin/visit-photo-review"

__all__ = [
    "ADMIN_DIR",
    "LIST_PATH",
    "LOGGER",
    "TEMPLATES",
    "Filters",
    "FilterChoice",
    "FilterDefect",
    "FilterGroup",
    "active_tab",
    "after_close_target",
    "avatar_error_message",
    "block_labels",
    "catalog_group_rows",
    "choice_rows",
    "content_filter_groups",
    "day_display",
    "day_iso_for_picker",
    "defect_rows_from_fields",
    "defects_error_message",
    "dispose_error_response",
    "facet_labels",
    "filters_from_request",
    "find_editor_group",
    "group_editor_page",
    "json_for_script",
    "mark_error_response",
    "matching_defect_code",
    "parse_day_param",
    "parse_group_editor_payload",
    "problem_options",
    "query_string",
    "review_submit_action",
    "save_error_response",
    "wants_json",
]
