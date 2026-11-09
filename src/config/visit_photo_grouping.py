from __future__ import annotations

import json
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from src.config._base import ServiceSettingsBase
from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    CatalogInvalid,
    parse_review_catalog,
    require_reserved_catalog_groups,
)

_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_RESERVED_REFERENCE_DIRS = frozenset({UNRECOGNIZED_GROUP_ID, POOR_QUALITY_GROUP_ID})


def _reference_has_group_images(pack_dir: Path) -> bool:
    reference = pack_dir / "reference"
    if not reference.is_dir():
        return False
    for group_dir in reference.iterdir():
        if not group_dir.is_dir() or group_dir.name in _RESERVED_REFERENCE_DIRS:
            continue
        for candidate in group_dir.iterdir():
            if candidate.is_file() and candidate.suffix.lower() in _IMAGE_SUFFIXES:
                return True
    return False


class VisitPhotoGroupingSettings(ServiceSettingsBase):
    enabled: bool = Field(
        default=False,
        validation_alias="VISIT_PHOTO_GROUPING_ENABLED",
    )
    worker_enabled: bool = Field(
        default=False,
        validation_alias="VISIT_PHOTO_GROUPING_WORKER_ENABLED",
    )
    pack_dir: str = Field(
        default="",
        validation_alias="VISIT_PHOTO_GROUPING_PACK_DIR",
    )
    packs_root: str = Field(
        default="",
        validation_alias="VISIT_PHOTO_GROUPING_PACKS_ROOT",
    )
    weights_path: str = Field(
        default="",
        validation_alias="VISIT_PHOTO_GROUPING_WEIGHTS_PATH",
    )
    catalog_path: str = Field(
        default="",
        validation_alias="VISIT_PHOTO_REVIEW_CATALOG_PATH",
    )
    reference_learned_max_per_group: int = Field(
        default=200,
        validation_alias="VISIT_PHOTO_REFERENCE_LEARNED_MAX_PER_GROUP",
    )
    not_ready_retry_minutes: int = Field(
        default=5,
        validation_alias="VISIT_PHOTO_GROUPING_NOT_READY_RETRY_MINUTES",
        ge=1,
    )
    not_ready_max_attempts: int = Field(
        default=24,
        validation_alias="VISIT_PHOTO_GROUPING_NOT_READY_MAX_ATTEMPTS",
        ge=1,
    )

    @model_validator(mode="after")
    def validate_when_enabled(self) -> Self:
        if not self.enabled:
            return self
        if not self.catalog_path.strip():
            raise ValueError(
                "VISIT_PHOTO_REVIEW_CATALOG_PATH must be set when "
                "VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        catalog_file = Path(self.catalog_path)
        if not catalog_file.is_file():
            raise ValueError(
                f"VISIT_PHOTO_REVIEW_CATALOG_PATH file not found: {self.catalog_path}",
            )
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"VISIT_PHOTO_REVIEW_CATALOG_PATH is not valid JSON: {exc}",
            ) from exc
        try:
            catalog = parse_review_catalog(payload)
            require_reserved_catalog_groups(catalog)
        except CatalogInvalid as exc:
            raise ValueError(str(exc)) from exc

        resolved_root = self.resolved_packs_root()
        if resolved_root is None:
            raise ValueError(
                "VISIT_PHOTO_GROUPING_PACKS_ROOT (or legacy "
                "VISIT_PHOTO_GROUPING_PACK_DIR) must be set when "
                "VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        if not resolved_root.is_dir():
            raise ValueError(
                f"VISIT_PHOTO_GROUPING packs root not found: {resolved_root}",
            )
        # Multi-pack root: images under {root}/{pack_key}/reference/.
        if self.packs_root.strip():
            return self
        # Legacy single PACK_DIR: require images in that pack tree.
        legacy_pack = Path(self.pack_dir.strip())
        if not legacy_pack.is_dir() or not _reference_has_group_images(legacy_pack):
            raise ValueError(
                "VISIT_PHOTO_GROUPING_PACK_DIR/reference must contain at least "
                "one group directory with image files",
            )
        return self

    def resolved_packs_root(self) -> Path | None:
        """Prefer PACKS_ROOT; else parent of PACK_DIR (pack_key = basename)."""
        root = self.packs_root.strip()
        if root:
            return Path(root)
        legacy = self.pack_dir.strip()
        if not legacy:
            return None
        pack_path = Path(legacy)
        parent = pack_path.parent
        if parent == pack_path:
            return pack_path
        return parent

    def legacy_default_pack_key(self) -> str | None:
        """Basename of PACK_DIR when PACKS_ROOT is unset."""
        if self.packs_root.strip():
            return None
        legacy = self.pack_dir.strip()
        if not legacy:
            return None
        return Path(legacy).name or None


class _ClassifierGate(ServiceSettingsBase):
    enabled: bool
    classifier_present: bool

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.enabled and not self.classifier_present:
            raise ValueError(
                "GroupClassifier is required when VISIT_PHOTO_GROUPING_ENABLED=true",
            )
        return self


def require_grouping_classifier[T](enabled: bool, classifier: T | None) -> T | None:
    _ClassifierGate(enabled=enabled, classifier_present=classifier is not None)
    if not enabled:
        return None
    return classifier
