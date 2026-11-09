from __future__ import annotations

import re
import uuid
from pathlib import Path

from beartype import beartype

from src.application.visit_photo_review.profile import ProfileTechRefStorageError

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})


@beartype
class FilesystemVisitPhotoProfileTechRefStorage:
    """Tech-ref files under ``{root}/{profile_id}/{key}`` (SoT for admin)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def list_keys(self, profile_id: str) -> tuple[str, ...]:
        directory = self._profile_dir(profile_id)
        if not directory.is_dir():
            return ()
        keys = sorted(
            path.name
            for path in directory.iterdir()
            if path.is_file() and _SAFE_KEY.fullmatch(path.name)
        )
        return tuple(keys)

    def save(
        self,
        profile_id: str,
        *,
        filename: str,
        payload: bytes,
    ) -> str:
        if not payload:
            raise ProfileTechRefStorageError("tech_ref_empty")
        suffix = Path(filename).suffix.lower()
        if suffix not in _IMAGE_SUFFIXES:
            raise ProfileTechRefStorageError("tech_ref_type_invalid")
        key = f"{uuid.uuid4().hex}{suffix}"
        directory = self._profile_dir(profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / key
        target.write_bytes(payload)
        return key

    def delete(self, profile_id: str, key: str) -> None:
        if not _SAFE_KEY.fullmatch(key):
            raise ProfileTechRefStorageError("tech_ref_key_invalid")
        path = self._profile_dir(profile_id) / key
        if not path.is_file():
            raise ProfileTechRefStorageError("tech_ref_missing")
        path.unlink()

    def read_bytes(self, profile_id: str, key: str) -> bytes:
        if not _SAFE_KEY.fullmatch(key):
            raise ProfileTechRefStorageError("tech_ref_key_invalid")
        path = self._profile_dir(profile_id) / key
        if not path.is_file():
            raise ProfileTechRefStorageError("tech_ref_missing")
        return path.read_bytes()

    def _profile_dir(self, profile_id: str) -> Path:
        if not _SAFE_KEY.fullmatch(profile_id):
            raise ProfileTechRefStorageError("profile_id_invalid")
        return self._root / profile_id
