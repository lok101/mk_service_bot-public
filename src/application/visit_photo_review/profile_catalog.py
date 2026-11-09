from __future__ import annotations

from beartype import beartype

from src.application.visit_photo_review.profile import VisitPhotoProfile
from src.domain.visit_photo_review import CatalogGroup, DefectButton, ReviewCatalog


@beartype
def review_catalog_from_profile(profile: VisitPhotoProfile) -> ReviewCatalog:
    """Project profile Mongo groups into the review/grouping ReviewCatalog shape."""
    return ReviewCatalog(
        groups=tuple(
            CatalogGroup(
                group_id=group.group_id,
                title=group.title,
                required=group.required,
                defects=tuple(
                    DefectButton(code=defect.code, label=defect.label) for defect in group.defects
                ),
            )
            for group in profile.groups
        )
    )
