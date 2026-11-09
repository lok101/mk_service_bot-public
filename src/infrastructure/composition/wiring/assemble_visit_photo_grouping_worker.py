from __future__ import annotations

from beartype import beartype

from src.config.settings import Settings, get_settings
from src.infrastructure.composition.visit_photo_grouping_worker_container import (
    VisitPhotoGroupingWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence
from src.infrastructure.composition.wiring.wire_visit_photo_grouping_worker import (
    wire_visit_photo_grouping_worker,
)
from src.infrastructure.visit_photo_grouping.openclip_classifier import ImageBytesEncoder


@beartype
def assemble_visit_photo_grouping_worker(
    settings: Settings | None = None,
    *,
    encoder: ImageBytesEncoder | None = None,
) -> VisitPhotoGroupingWorkerContainer:
    resolved = settings or get_settings()
    persistence = wire_persistence(resolved)
    return wire_visit_photo_grouping_worker(
        resolved,
        persistence=persistence,
        encoder=encoder,
    )
