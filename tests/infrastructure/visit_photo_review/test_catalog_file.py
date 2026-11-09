from __future__ import annotations

import json

import pytest

from src.application.visit_photo_review.commands import UpdateGroupDefects
from src.application.visit_photo_review.ports import CatalogUnavailable
from src.domain.visit_photo_review import DefectButton
from src.infrastructure.visit_photo_review.catalog_file import FileReviewCatalog


def test_catalog_file_reread_sees_new_label(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        '{"groups":[{"group_id":"waste_tank","title":"Бак","required":true,"defects":[{"code":"dirty","label":"Грязь"}]}]}',
        encoding="utf-8",
    )
    source = FileReviewCatalog(path)
    assert source.load().groups[0].defects[0].label == "Грязь"
    path.write_text(
        '{"groups":[{"group_id":"waste_tank","title":"Бак","required":true,"defects":[{"code":"dirty","label":"Пыль"}]}]}',
        encoding="utf-8",
    )
    assert source.load().groups[0].defects[0].label == "Пыль"


def test_catalog_file_broken_after_start_raises(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        '{"groups":[{"group_id":"waste_tank","title":"Бак","required":true,"defects":[]}]}',
        encoding="utf-8",
    )
    source = FileReviewCatalog(path)
    source.load()
    path.write_text("{", encoding="utf-8")
    with pytest.raises(CatalogUnavailable):
        source.load()


def test_update_group_defects_rewrites_catalog_json(tmp_path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_id": "waste_tank",
                        "title": "Бак",
                        "required": True,
                        "defects": [{"code": "dirty", "label": "Грязь"}],
                    },
                    {
                        "group_id": "cup",
                        "title": "Стакан",
                        "required": False,
                        "defects": [],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    catalog = FileReviewCatalog(path)
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (("dirty", "Пыль"), ("rust", "Ржавчина")),
    )
    assert result.is_ok()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["groups"][0]["title"] == "Бак"
    assert payload["groups"][0]["required"] is True
    assert payload["groups"][0]["defects"] == [
        {"code": "dirty", "label": "Пыль"},
        {"code": "rust", "label": "Ржавчина"},
    ]
    assert payload["groups"][1] == {
        "group_id": "cup",
        "title": "Стакан",
        "required": False,
        "defects": [],
    }
    reloaded = catalog.load().group("waste_tank")
    assert reloaded is not None
    assert reloaded.defects == (
        DefectButton(code="dirty", label="Пыль"),
        DefectButton(code="rust", label="Ржавчина"),
    )
