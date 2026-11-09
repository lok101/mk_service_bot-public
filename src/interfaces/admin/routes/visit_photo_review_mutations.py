from __future__ import annotations

from typing import Any

from beartype import beartype
from fastapi import APIRouter

from src.application.visit_photo_review import RecordFrameView, ReviewQueries
from src.interfaces.admin.deps import AdminHttpDeps
from src.interfaces.admin.routes.visit_photo_review_mutation_blocks import (
    register_visit_photo_review_mutation_block_routes,
)
from src.interfaces.admin.routes.visit_photo_review_mutation_groups import (
    register_visit_photo_review_mutation_group_routes,
)

__all__ = ["register_visit_photo_review_mutation_routes"]


@beartype
def register_visit_photo_review_mutation_routes(
    router: APIRouter,
    deps: AdminHttpDeps,
    *,
    queries: ReviewQueries,
    store: Any,
    record_frame_view: RecordFrameView,
) -> None:
    register_visit_photo_review_mutation_group_routes(router, deps, queries=queries)
    register_visit_photo_review_mutation_block_routes(
        router,
        deps,
        queries=queries,
        store=store,
        record_frame_view=record_frame_view,
    )
