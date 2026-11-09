from __future__ import annotations

from beartype import beartype
from fastapi import APIRouter

from src.application.visit_photo_review import RecordFrameView
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.visit_photo_review_group_editor import (
    find_editor_group as _find_editor_group,
)
from src.interfaces.admin.routes.visit_photo_review_http import (
    review_submit_action,
)
from src.interfaces.admin.routes.visit_photo_review_mutations import (
    register_visit_photo_review_mutation_routes,
)
from src.interfaces.admin.routes.visit_photo_review_queries import (
    register_visit_photo_review_query_routes,
)

# Re-export for tests that monkeypatch `visit_photo_review._find_editor_group`.
__all__ = [
    "register_visit_photo_review_routes",
    "review_submit_action",
    "_find_editor_group",
]


@beartype
def register_visit_photo_review_routes(router: APIRouter, deps: AdminHttpDeps) -> None:
    if not deps.visit_photo_review_enabled or deps.review_queries is None:
        return

    queries = deps.review_queries
    catalog_source = queries._catalog
    store = queries._store
    record_frame_view = RecordFrameView(store=store, clock=deps.now_factory)

    register_visit_photo_review_query_routes(
        router,
        deps,
        queries=queries,
        catalog_source=catalog_source,
        store=store,
    )
    register_visit_photo_review_mutation_routes(
        router,
        deps,
        queries=queries,
        store=store,
        record_frame_view=record_frame_view,
    )
