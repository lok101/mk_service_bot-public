from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from scripts.coffee_recipes_domain_prepare_lib import (
    _parse_drink_by_bundle,
    _parse_ingredient_by_ms,
    load_legacy_recipes_json,
    write_template_csvs,
)
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity import CatalogProduct

_FIXTURE = Path("tests/fixtures/coffee_recipes/sample.json")


def test_load_legacy_recipes_json_sample() -> None:
    recipes = load_legacy_recipes_json(_FIXTURE)
    assert len(recipes) == 1
    assert recipes[0].bundle_code == "2301"
    assert recipes[0].components[0].product_code == "coffee-1"
    assert recipes[0].components[0].quantity_per_unit == Decimal("30")


def test_write_template_csvs(tmp_path: Path) -> None:
    recipes = load_legacy_recipes_json(_FIXTURE)
    paths = write_template_csvs(recipes, out_dir=tmp_path)
    drinks_text = paths.drinks.read_text(encoding="utf-8-sig")
    ingredients_text = paths.ingredients.read_text(encoding="utf-8-sig")
    lines_text = paths.recipe_lines.read_text(encoding="utf-8-sig")
    assert "drink_domain_number" in drinks_text
    assert "2301" in drinks_text
    assert "ingredient_domain_number" in ingredients_text
    assert "coffee-1" in ingredients_text
    assert "quantity_per_unit" in lines_text


def test_parse_drink_by_bundle_allocates_when_domain_number_empty() -> None:
    recipes = load_legacy_recipes_json(_FIXTURE)
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    reserved: list[str] = []
    mapping = _parse_drink_by_bundle(
        [{"bundle_code": "101", "drink_name": "Latte", "drink_domain_number": ""}],
        recipes,
        store=store,
        lookup=lookup,
        reserved=reserved,
    )
    assert mapping["101"][0] == "Latte"
    assert mapping["101"][1] == "d-1"
    assert mapping["2301"][1] == "d-2"


def test_parse_ingredient_by_ms_adds_codes_from_recipes_and_catalog_name() -> None:
    recipes = load_legacy_recipes_json(_FIXTURE)
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (CatalogProduct(code="coffee-1", name="  Зерно  ", archived=False),),
    )
    reserved: list[str] = []
    mapping = _parse_ingredient_by_ms(
        [],
        recipes,
        store=store,
        lookup=lookup,
        reserved=reserved,
    )
    assert mapping["coffee-1"] == ("Зерно", "d-1")
