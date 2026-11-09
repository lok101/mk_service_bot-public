from __future__ import annotations

from beartype import beartype

from src.application.visit_photo_review.ports import CatalogUnavailable, ReviewCatalogSource
from src.application.visit_photo_review.profile import ResolveVisitPhotoProfile, VisitPhotoProfile
from src.application.visit_photo_review.profile_catalog import review_catalog_from_profile
from src.domain.visit_photo_review import ReviewCatalog
from src.infrastructure.visit_photo_review.catalog_file import FileReviewCatalog


@beartype
class ProfilePreferringReviewCatalog:
    """Resolve ReviewCatalog from visit photo profile; shared file is cutover fallback.

    ``load()`` without machine context still reads the deprecated shared JSON path.
    Grouping/review commands that know ``machine_id`` must call ``load_for_machine``.
    """

    def __init__(
        self,
        file_catalog: FileReviewCatalog | ReviewCatalogSource,
        resolve: ResolveVisitPhotoProfile | None,
        *,
        profile_strict: bool,
    ) -> None:
        self._file = file_catalog
        self._resolve = resolve
        self._profile_strict = profile_strict

    @beartype
    def load(self) -> ReviewCatalog:
        return self._file.load()

    @beartype
    def load_for_machine(self, machine_id: str) -> ReviewCatalog:
        profile = self._resolve_profile(machine_id)
        if profile is not None:
            return review_catalog_from_profile(profile)
        if self._profile_strict and self._resolve is not None and self._is_coffee(machine_id):
            raise CatalogUnavailable("visit_photo_profile_missing")
        return self._file.load()

    def _resolve_profile(self, machine_id: str) -> VisitPhotoProfile | None:
        if self._resolve is None:
            return None
        profile = self._resolve(machine_id)
        if profile is not None:
            return profile
        if self._profile_strict:
            return None
        if self._is_coffee(machine_id):
            return self._resolve.default_profile()
        return None

    def _is_coffee(self, machine_id: str) -> bool:
        if self._resolve is None:
            return False
        facts = self._resolve.machines.equipment_of(machine_id)
        return facts is not None and facts.kind == "coffee"
