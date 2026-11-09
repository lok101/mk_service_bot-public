from __future__ import annotations

from fastapi import APIRouter

from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.micromarket_planogram_access import (
    _PATH_ALLOWED_CODES_CACHE,
    _PATH_ALLOWED_CODES_FAILED_AT,
    _path_allowed_codes,
)
from src.interfaces.admin.routes.micromarket_planogram_context import _planogram_tab_context
from src.interfaces.admin.routes.micromarket_planogram_mutations import (
    register_micromarket_planogram_mutation_routes,
)
from src.interfaces.admin.routes.micromarket_planogram_parse import _parse_planogram_form
from src.interfaces.admin.routes.micromarket_planogram_publish import (
    register_micromarket_planogram_publish_routes,
)

__all__ = [
    "register_micromarket_planogram_routes",
    "_PATH_ALLOWED_CODES_CACHE",
    "_PATH_ALLOWED_CODES_FAILED_AT",
    "_parse_planogram_form",
    "_path_allowed_codes",
    "_planogram_tab_context",
]


def register_micromarket_planogram_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    register_micromarket_planogram_mutation_routes(router, deps)
    register_micromarket_planogram_publish_routes(router, deps)
