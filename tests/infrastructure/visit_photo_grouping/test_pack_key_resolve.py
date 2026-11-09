from __future__ import annotations

from pathlib import Path

import pytest

from src.application.visit_photo_grouping.pack_path import resolve_visit_photo_pack_dir
from src.config.visit_photo_grouping import VisitPhotoGroupingSettings


def test_resolve_visit_photo_pack_dir_joins_root_and_key(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    assert resolve_visit_photo_pack_dir(root, "coffee_g23") == root / "coffee_g23"


def test_resolve_visit_photo_pack_dir_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="invalid pack_key"):
        resolve_visit_photo_pack_dir(Path("/packs"), "../other")


def test_legacy_pack_dir_alias_to_root_and_key(tmp_path: Path) -> None:
    pack = tmp_path / "visit-photo-pack"
    pack.mkdir()
    (pack / "reference").mkdir()
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        VISIT_PHOTO_GROUPING_PACKS_ROOT="",
    )
    assert settings.resolved_packs_root() == pack.parent
    assert settings.legacy_default_pack_key() == "visit-photo-pack"
    root = settings.resolved_packs_root()
    key = settings.legacy_default_pack_key()
    assert root is not None and key is not None
    assert resolve_visit_photo_pack_dir(root, key) == pack


def test_packs_root_prefers_explicit_root(tmp_path: Path) -> None:
    root = tmp_path / "roots"
    root.mkdir()
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_PACKS_ROOT=str(root),
        VISIT_PHOTO_GROUPING_PACK_DIR=str(tmp_path / "ignored"),
    )
    assert settings.resolved_packs_root() == root
    assert settings.legacy_default_pack_key() is None
