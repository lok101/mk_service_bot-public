from __future__ import annotations

import hashlib
import re
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_review.ports import (
    AvatarPackUnavailable,
    GroupAvatar,
    LearnedAppendSkipped,
)

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_SUFFIX_FOR_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _is_safe_group_id(group_id: str) -> bool:
    if not group_id:
        return False
    return "/" not in group_id and "\\" not in group_id and ".." not in group_id


def _normalize_pack_dir(pack_dir: Path | str | None) -> Path | None:
    if pack_dir is None:
        return None
    text = str(pack_dir).strip()
    return Path(text) if text else None


def _suffix_for_content(content: bytes, content_type: str) -> str:
    normalized = content_type.split(";", maxsplit=1)[0].strip().lower()
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    return _SUFFIX_FOR_CONTENT_TYPE.get(normalized, ".jpg")


def _resolve_group_dir(pack_dir: Path, group_id: str) -> Path:
    if not _is_safe_group_id(group_id):
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


def _is_avatar_filename(name: str) -> bool:
    stem = Path(name).stem.lower()
    return stem == "avatar"


def _is_learned_filename(name: str) -> bool:
    return name.lower().startswith("learned-")


def _safe_batch_token(batch_id: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("-", batch_id.strip())
    return cleaned or "batch"


def _iter_group_images(group_dir: Path) -> list[Path]:
    if not group_dir.is_dir():
        return []
    return sorted(
        path
        for path in group_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )


def _prefer_avatar(images: list[Path]) -> Path | None:
    for path in images:
        if _is_avatar_filename(path.name):
            return path
    return images[0] if images else None


@beartype
class PackDirGroupAvatarReader:
    def __init__(self, pack_dir: Path | str | None) -> None:
        self._pack_dir = _normalize_pack_dir(pack_dir)

    def read_avatar(self, group_id: str) -> GroupAvatar | None:
        if self._pack_dir is None:
            return None
        if not _is_safe_group_id(group_id):
            return None
        try:
            group_dir = _resolve_group_dir(self._pack_dir, group_id)
        except ValueError:
            return None
        if not group_dir.is_dir():
            return None
        chosen = _prefer_avatar(_iter_group_images(group_dir))
        if chosen is None:
            return None
        return GroupAvatar(
            content=chosen.read_bytes(),
            content_type=_CONTENT_TYPES[chosen.suffix.lower()],
        )


@beartype
class PackDirGroupAvatarWriter:
    def __init__(self, pack_dir: Path | str | None) -> None:
        self._pack_dir = _normalize_pack_dir(pack_dir)

    @beartype
    def write_avatar(self, group_id: str, content: bytes, content_type: str) -> None:
        if self._pack_dir is None:
            raise AvatarPackUnavailable("pack dir not configured")
        group_dir = _resolve_group_dir(self._pack_dir, group_id)
        group_dir.mkdir(parents=True, exist_ok=True)
        for path in list(group_dir.iterdir()):
            if (
                path.is_file()
                and path.suffix.lower() in _IMAGE_SUFFIXES
                and _is_avatar_filename(path.name)
            ):
                path.unlink()
        suffix = _suffix_for_content(content, content_type)
        target = group_dir / f"avatar{suffix}"
        target.write_bytes(content)


@beartype
class PackDirLearnedReferenceWriter:
    def __init__(self, pack_dir: Path | str | None) -> None:
        self._pack_dir = _normalize_pack_dir(pack_dir)

    @beartype
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
        if self._pack_dir is None:
            raise AvatarPackUnavailable("pack dir not configured")
        group_dir = _resolve_group_dir(self._pack_dir, group_id)
        group_dir.mkdir(parents=True, exist_ok=True)

        content_hash = hashlib.sha256(content).hexdigest()
        for path in _iter_group_images(group_dir):
            if hashlib.sha256(path.read_bytes()).hexdigest() == content_hash:
                raise LearnedAppendSkipped("skip_dup")

        learned_files = [
            path for path in _iter_group_images(group_dir) if _is_learned_filename(path.name)
        ]
        suffix = _suffix_for_content(content, content_type)
        target = group_dir / f"learned-{_safe_batch_token(batch_id)}-{index}{suffix}"
        if len(learned_files) >= max_per_group and not target.exists():
            raise LearnedAppendSkipped("skip_cap")

        target.write_bytes(content)
