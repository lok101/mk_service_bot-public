from __future__ import annotations

from src.application.visit_photo_review.profile import (
    ProfileGroupDefect,
    VisitPhotoProfile,
    VisitPhotoProfileGroup,
    VisitPhotoProfileMember,
    seed_service_groups,
)
from src.application.visit_photo_review.profile_catalog import review_catalog_from_profile
from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    TRASH_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
)


def test_review_catalog_from_profile_maps_groups_and_defects() -> None:
    groups = seed_service_groups() + (
        VisitPhotoProfileGroup(
            group_id="before",
            title="До обслуживания",
            required=True,
            defects=(ProfileGroupDefect(code="dirty", label="Грязь"),),
            photo_only=False,
        ),
    )
    profile = VisitPhotoProfile(
        profile_id="p1",
        name="G23",
        members=frozenset({VisitPhotoProfileMember(model_id="m", stand_type_id=None)}),
        groups=groups,
        pack_key="g23",
    )
    catalog = review_catalog_from_profile(profile)
    assert catalog.group("before") is not None
    assert catalog.group("before").title == "До обслуживания"
    assert catalog.group("before").required is True
    assert catalog.group("before").defects[0].code == "dirty"
    assert catalog.group("before").defects[0].label == "Грязь"
    assert catalog.group(TRASH_GROUP_ID) is not None
    assert catalog.group(POOR_QUALITY_GROUP_ID) is not None
    assert catalog.group(UNRECOGNIZED_GROUP_ID) is not None
