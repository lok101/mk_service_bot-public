from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_grouping.pack_path import resolve_visit_photo_pack_dir
from src.application.visit_photo_review.ports import (
    AcceptedBatchReader,
    AvatarPackUnavailable,
    GroupAvatar,
)
from src.application.visit_photo_review.profile import (
    ResolveVisitPhotoProfile,
)
from src.infrastructure.visit_photo_review.group_avatar import (
    PackDirGroupAvatarReader,
    PackDirGroupAvatarWriter,
    PackDirLearnedReferenceWriter,
)


def _safe_group_reference_dir(pack_dir: Path, group_id: str) -> Path:
    if not group_id or "/" in group_id or "\\" in group_id or ".." in group_id:
        msg = f"unsafe group_id: {group_id!r}"
        raise ValueError(msg)
    reference_root = (pack_dir / "reference").resolve()
    group_dir = (reference_root / group_id).resolve()
    try:
        group_dir.relative_to(reference_root)
    except ValueError as exc:
        msg = f"unsafe group_id: {group_id!r}"
        raise ValueError(msg) from exc
    return group_dir


@beartype
def ensure_group_reference_dir(pack_dir: Path, group_id: str) -> Path:
    """Create empty ``reference/<group_id>/`` under pack_dir (idempotent)."""
    group_dir = _safe_group_reference_dir(pack_dir, group_id)
    group_dir.mkdir(parents=True, exist_ok=True)
    return group_dir


@beartype
@dataclass(slots=True)
class FilesystemProfileGroupReferenceLayout:
    packs_root: Path

    def ensure_dirs(self, pack_key: str, group_ids: tuple[str, ...]) -> None:
        pack_dir = resolve_visit_photo_pack_dir(self.packs_root, pack_key)
        pack_dir.mkdir(parents=True, exist_ok=True)
        for group_id in group_ids:
            ensure_group_reference_dir(pack_dir, group_id)


@beartype
@dataclass(slots=True)
class ProfilePackPathResolver:
    """Resolve ``{packs_root}/{pack_key}`` for a batch machine (or fallback)."""

    packs_root: Path | None
    batches: AcceptedBatchReader
    resolve_profile: ResolveVisitPhotoProfile | None
    profile_strict: bool
    legacy_default_pack_key: str | None
    legacy_pack_dir: Path | None

    def pack_dir_for_batch(self, batch_id: str) -> Path | None:
        pack_key = self._pack_key_for_batch(batch_id)
        if pack_key is not None and self.packs_root is not None:
            try:
                return resolve_visit_photo_pack_dir(self.packs_root, pack_key)
            except ValueError:
                return None
        return self.legacy_pack_dir

    def fallback_pack_dir(self) -> Path | None:
        if self.packs_root is not None:
            key = self.legacy_default_pack_key
            if key is None and self.resolve_profile is not None:
                default = self.resolve_profile.default_profile()
                if default is not None:
                    key = default.pack_key
            if key is not None:
                try:
                    return resolve_visit_photo_pack_dir(self.packs_root, key)
                except ValueError:
                    return None
        return self.legacy_pack_dir

    def _pack_key_for_batch(self, batch_id: str) -> str | None:
        batch = self.batches.get(batch_id)
        if batch is None:
            return self.legacy_default_pack_key
        if self.resolve_profile is not None:
            profile = self.resolve_profile(batch.machine_id)
            if profile is None and not self.profile_strict:
                profile = self.resolve_profile.default_profile()
            if profile is not None:
                return profile.pack_key
            if self.profile_strict:
                return None
        return self.legacy_default_pack_key


@beartype
@dataclass(slots=True)
class ProfileResolvingLearnedReferenceWriter:
    paths: ProfilePackPathResolver

    def append_learned(
        self,
        *,
        group_id: str,
        batch_id: str,
        index: int,
        content: bytes,
        content_type: str,
        max_per_group: int,
    ) -> None:
        pack_dir = self.paths.pack_dir_for_batch(batch_id)
        if pack_dir is None:
            raise AvatarPackUnavailable("pack dir not configured")
        PackDirLearnedReferenceWriter(pack_dir).append_learned(
            group_id=group_id,
            batch_id=batch_id,
            index=index,
            content=content,
            content_type=content_type,
            max_per_group=max_per_group,
        )


@beartype
@dataclass(slots=True)
class ProfileResolvingGroupAvatarWriter:
    paths: ProfilePackPathResolver

    def write_avatar(self, group_id: str, content: bytes, content_type: str) -> None:
        pack_dir = self.paths.fallback_pack_dir()
        if pack_dir is None:
            raise AvatarPackUnavailable("pack dir not configured")
        PackDirGroupAvatarWriter(pack_dir).write_avatar(group_id, content, content_type)


@beartype
@dataclass(slots=True)
class ProfileResolvingGroupAvatarReader:
    paths: ProfilePackPathResolver

    def read_avatar(self, group_id: str) -> GroupAvatar | None:
        pack_dir = self.paths.fallback_pack_dir()
        if pack_dir is None:
            return None
        return PackDirGroupAvatarReader(pack_dir).read_avatar(group_id)
