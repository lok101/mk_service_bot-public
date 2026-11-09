from __future__ import annotations

import pytest

from src.domain.visit_photo_review import (
    POOR_QUALITY_GROUP_ID,
    UNRECOGNIZED_GROUP_ID,
    CatalogInvalid,
    parse_review_catalog,
    require_reserved_catalog_groups,
)


def test_parse_review_catalog_reads_group_order() -> None:
    catalog = parse_review_catalog(
        {
            "groups": [
                {
                    "group_id": "waste_tank",
                    "title": "Бак отходов",
                    "required": True,
                    "defects": [{"code": "dirty", "label": "Грязь"}],
                }
            ]
        }
    )
    assert catalog.groups[0].group_id == "waste_tank"
    assert catalog.groups[0].required is True
    assert catalog.groups[0].defects[0].label == "Грязь"
    assert catalog.order_index("waste_tank") == 0


def test_parse_review_catalog_rejects_duplicate_group_id() -> None:
    with pytest.raises(CatalogInvalid):
        parse_review_catalog(
            {
                "groups": [
                    {"group_id": "a", "title": "A", "required": False, "defects": []},
                    {"group_id": "a", "title": "B", "required": False, "defects": []},
                ]
            }
        )


def test_parse_review_catalog_rejects_duplicate_defect_code() -> None:
    with pytest.raises(CatalogInvalid):
        parse_review_catalog(
            {
                "groups": [
                    {
                        "group_id": "a",
                        "title": "A",
                        "required": False,
                        "defects": [
                            {"code": "dirty", "label": "Грязь"},
                            {"code": "dirty", "label": "Другая"},
                        ],
                    }
                ]
            }
        )


def test_parse_review_catalog_allows_group_without_defects() -> None:
    catalog = parse_review_catalog(
        {"groups": [{"group_id": "cup", "title": "Стакан", "defects": []}]}
    )
    assert catalog.groups[0].defects == ()
    assert catalog.groups[0].required is False


def test_parse_review_catalog_rejects_empty_groups() -> None:
    with pytest.raises(CatalogInvalid):
        parse_review_catalog({"groups": []})


def test_reserved_group_id_constants() -> None:
    assert UNRECOGNIZED_GROUP_ID == "unrecognized"
    assert POOR_QUALITY_GROUP_ID == "poor_quality"


def test_require_reserved_catalog_groups_accepts_optional_reserved() -> None:
    catalog = parse_review_catalog(
        {
            "groups": [
                {
                    "group_id": "cup",
                    "title": "Стакан",
                    "required": True,
                    "defects": [],
                },
                {
                    "group_id": "unrecognized",
                    "title": "Не удалось определить",
                    "required": False,
                    "defects": [],
                },
                {
                    "group_id": "poor_quality",
                    "title": "Некачественные фото",
                    "required": False,
                    "defects": [],
                },
            ]
        }
    )
    require_reserved_catalog_groups(catalog)


def test_require_reserved_catalog_groups_rejects_missing_unrecognized() -> None:
    catalog = parse_review_catalog(
        {
            "groups": [
                {
                    "group_id": "poor_quality",
                    "title": "Некачественные фото",
                    "required": False,
                    "defects": [],
                }
            ]
        }
    )
    with pytest.raises(CatalogInvalid, match="unrecognized"):
        require_reserved_catalog_groups(catalog)


def test_require_reserved_catalog_groups_rejects_required_reserved() -> None:
    catalog = parse_review_catalog(
        {
            "groups": [
                {
                    "group_id": "unrecognized",
                    "title": "Не удалось определить",
                    "required": True,
                    "defects": [],
                },
                {
                    "group_id": "poor_quality",
                    "title": "Некачественные фото",
                    "required": False,
                    "defects": [],
                },
            ]
        }
    )
    with pytest.raises(CatalogInvalid, match="required"):
        require_reserved_catalog_groups(catalog)
