from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.config.test_visit_photo_review_settings import _stub_required_app_env

from src.config.settings import Settings
from src.config.visit_photo_grouping import (
    VisitPhotoGroupingSettings,
    require_grouping_classifier,
)

_VALID_WITH_RESERVED = (
    '{"groups":['
    '{"group_id":"a","title":"A","required":true,"defects":[]},'
    '{"group_id":"unrecognized","title":"Не удалось определить","required":false,"defects":[]},'
    '{"group_id":"poor_quality","title":"Некачественные фото","required":false,"defects":[]}'
    "]}"
)

_VALID_WITHOUT_RESERVED = '{"groups":[{"group_id":"a","title":"A","required":true,"defects":[]}]}'


def _write_catalog(tmp_path: Path, body: str = _VALID_WITH_RESERVED) -> Path:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(body, encoding="utf-8")
    return catalog


def _write_pack_with_reference(tmp_path: Path) -> Path:
    pack = tmp_path / "pack"
    group = pack / "reference" / "a"
    group.mkdir(parents=True)
    (group / "sample.jpg").write_bytes(b"fake-jpeg")
    return pack


def test_grouping_disabled_does_not_require_catalog() -> None:
    settings = VisitPhotoGroupingSettings()
    assert settings.enabled is False
    assert settings.catalog_path == ""
    assert settings.pack_dir == ""
    assert settings.worker_enabled is False
    assert settings.weights_path == ""


def test_reference_learned_max_per_group_defaults_to_200() -> None:
    settings = VisitPhotoGroupingSettings()
    assert settings.reference_learned_max_per_group == 200


def test_reference_learned_max_per_group_explicit_override() -> None:
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_REFERENCE_LEARNED_MAX_PER_GROUP="50",
    )
    assert settings.reference_learned_max_per_group == 50


def test_not_ready_retry_defaults() -> None:
    settings = VisitPhotoGroupingSettings()
    assert settings.not_ready_retry_minutes == 5
    assert settings.not_ready_max_attempts == 24


def test_not_ready_retry_explicit_override() -> None:
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_NOT_READY_RETRY_MINUTES="10",
        VISIT_PHOTO_GROUPING_NOT_READY_MAX_ATTEMPTS="48",
    )
    assert settings.not_ready_retry_minutes == 10
    assert settings.not_ready_max_attempts == 48


def test_grouping_enabled_rejects_missing_catalog(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    pack = _write_pack_with_reference(tmp_path)
    with pytest.raises(ValidationError):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(missing),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_empty_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"groups":[]}', encoding="utf-8")
    pack = _write_pack_with_reference(tmp_path)
    with pytest.raises(ValidationError):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_invalid_json(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{", encoding="utf-8")
    pack = _write_pack_with_reference(tmp_path)
    with pytest.raises(ValidationError):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_missing_pack_dir(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    with pytest.raises(ValidationError, match="PACK_DIR"):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR="",
        )


def test_grouping_enabled_rejects_empty_reference(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    pack = tmp_path / "pack"
    (pack / "reference").mkdir(parents=True)
    with pytest.raises(ValidationError, match="reference"):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_reference_with_only_reserved_dirs(
    tmp_path: Path,
) -> None:
    catalog = _write_catalog(tmp_path)
    pack = tmp_path / "pack"
    for reserved in ("unrecognized", "poor_quality"):
        group = pack / "reference" / reserved
        group.mkdir(parents=True)
        (group / "sample.jpg").write_bytes(b"fake-jpeg")
    with pytest.raises(ValidationError, match="reference"):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_missing_pack_path(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    missing_pack = tmp_path / "missing-pack"
    with pytest.raises(ValidationError, match="PACK_DIR"):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(missing_pack),
        )


def test_grouping_enabled_accepts_pack_and_catalog(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    pack = _write_pack_with_reference(tmp_path)
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_ENABLED="true",
        VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
        VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
    )
    assert settings.enabled is True
    assert settings.pack_dir == str(pack)


def test_worker_enabled_defaults_false() -> None:
    settings = VisitPhotoGroupingSettings()
    assert settings.worker_enabled is False


def test_both_flags_true_without_pack_raises(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    with pytest.raises(ValidationError, match="PACK_DIR"):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_GROUPING_WORKER_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR="",
        )


def test_grouping_enabled_without_classifier_raises() -> None:
    with pytest.raises(ValidationError, match="GroupClassifier"):
        require_grouping_classifier(True, None)


def test_grouping_disabled_allows_missing_classifier() -> None:
    assert require_grouping_classifier(False, None) is None


def test_settings_grouping_on_does_not_require_review_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    catalog = _write_catalog(tmp_path)
    pack = _write_pack_with_reference(tmp_path)
    monkeypatch.setenv("VISIT_PHOTO_GROUPING_ENABLED", "true")
    monkeypatch.setenv("VISIT_PHOTO_REVIEW_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("VISIT_PHOTO_GROUPING_PACK_DIR", str(pack))
    monkeypatch.setenv("VISIT_PHOTO_REVIEW_ENABLED", "false")
    settings = Settings()
    assert settings.visit_photo_grouping.enabled is True
    assert settings.visit_photo_review.enabled is False


def test_grouping_enabled_rejects_catalog_without_reserved_groups(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(_VALID_WITHOUT_RESERVED, encoding="utf-8")
    pack = _write_pack_with_reference(tmp_path)
    with pytest.raises(ValidationError):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_rejects_required_reserved_group(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        '{"groups":['
        '{"group_id":"unrecognized","title":"Не удалось определить","required":true,"defects":[]},'
        '{"group_id":"poor_quality","title":"Некачественные фото","required":false,"defects":[]}'
        "]}",
        encoding="utf-8",
    )
    pack = _write_pack_with_reference(tmp_path)
    with pytest.raises(ValidationError):
        VisitPhotoGroupingSettings(
            VISIT_PHOTO_GROUPING_ENABLED="true",
            VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
            VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
        )


def test_grouping_enabled_accepts_optional_reserved_groups(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path)
    pack = _write_pack_with_reference(tmp_path)
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_ENABLED="true",
        VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
        VISIT_PHOTO_GROUPING_PACK_DIR=str(pack),
    )
    assert settings.enabled is True


def test_grouping_disabled_allows_catalog_without_reserved_groups(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(_VALID_WITHOUT_RESERVED, encoding="utf-8")
    settings = VisitPhotoGroupingSettings(
        VISIT_PHOTO_GROUPING_ENABLED="false",
        VISIT_PHOTO_REVIEW_CATALOG_PATH=str(catalog),
    )
    assert settings.enabled is False
