from __future__ import annotations

from src.application.form_submissions.form_quantities import load_product_specs_collecting_unknown
from src.infrastructure.testing.stubs import MappingProductCatalogResolver


def test_load_product_specs_resolves_icon_prefixed_form_titles() -> None:
    resolver = MappingProductCatalogResolver({"Концентрат": "concentrate-1"})
    titles = ("🟧 | Концентрат",)

    specs, unknown = load_product_specs_collecting_unknown(resolver, titles)

    assert unknown == ()
    assert specs["🟧 | Концентрат"].product_code == "concentrate-1"


def test_load_product_specs_keeps_plain_titles() -> None:
    resolver = MappingProductCatalogResolver({"Кофе": "coffee-1"})
    titles = ("Кофе",)

    specs, unknown = load_product_specs_collecting_unknown(resolver, titles)

    assert unknown == ()
    assert specs["Кофе"].product_code == "coffee-1"
