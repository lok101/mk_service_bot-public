from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_grouping.group_accepted_batch import GroupingRetryReason
from src.application.visit_photo_grouping.pack_path import resolve_visit_photo_pack_dir
from src.application.visit_photo_grouping.ports import (
    GroupingPermanentFailure,
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
)
from src.application.visit_photo_review.profile import ResolveVisitPhotoProfile
from src.infrastructure.visit_photo_grouping.openclip_classifier import (
    OpenClipGroupClassifier,
)


@beartype
@dataclass(slots=True)
class ProfileAwareGroupClassifier:
    """Selects ``{packs_root}/{pack_key}`` per batch machine before classify."""

    packs_root: Path
    machine_id_for_batch: Callable[[str], str | None]
    resolve_profile: ResolveVisitPhotoProfile | None
    profile_strict: bool
    legacy_default_pack_key: str | None
    build_classifier: Callable[[Path], OpenClipGroupClassifier]
    _cache: dict[str, OpenClipGroupClassifier] = field(default_factory=dict)

    def classify(
        self,
        batch_id: str,
        files: tuple[GroupingStoredFile, ...],
    ) -> GroupingSuccess | GroupingTemporaryFailure | GroupingPermanentFailure:
        machine_id = self.machine_id_for_batch(batch_id)
        pack_key = self._pack_key_for_machine(machine_id)
        if pack_key is None:
            return GroupingTemporaryFailure(
                reason_code=GroupingRetryReason.VISIT_PHOTO_PROFILE_MISSING.value,
            )
        try:
            pack_dir = resolve_visit_photo_pack_dir(self.packs_root, pack_key)
        except ValueError:
            return GroupingTemporaryFailure()
        if not pack_dir.is_dir():
            return GroupingTemporaryFailure()
        classifier = self._cache.get(pack_key)
        if classifier is None:
            classifier = self.build_classifier(pack_dir)
            self._cache[pack_key] = classifier
        return classifier.classify(batch_id, files)

    def _pack_key_for_machine(self, machine_id: str | None) -> str | None:
        if machine_id and self.resolve_profile is not None:
            profile = self.resolve_profile(machine_id)
            if profile is None and not self.profile_strict:
                profile = self.resolve_profile.default_profile()
            if profile is not None:
                return profile.pack_key
            if self.profile_strict:
                return None
        if self.legacy_default_pack_key:
            return self.legacy_default_pack_key
        if self.resolve_profile is not None and not self.profile_strict:
            default = self.resolve_profile.default_profile()
            if default is not None:
                return default.pack_key
        return None
