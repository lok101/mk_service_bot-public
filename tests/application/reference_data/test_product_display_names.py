from __future__ import annotations

from src.application.reference_data.ms_product_catalog import (
    MsEntityKind,
    MsProductEntry,
    ParsedMsProductCatalog,
)
from src.application.reference_data.product_display_names import (
    build_product_display_name_map,
    resolve_product_display_name,
)
from src.application.sheets.product_catalog import parse_product_catalog_sheet


def test_sales_display_ms_then_vitrine_fallback() -> None:
    ms = ParsedMsProductCatalog(
        by_code={
            "ms1": MsProductEntry("ms1", "MS Name", MsEntityKind.PRODUCT),
        },
        name_to_code={"MS Name": "ms1"},
    )
    vitrine = parse_product_catalog_sheet(
        [["id", "имя"], ["ms1", "Form Name"], ["only_v", "Only Vitrine"]],
    )
    assert resolve_product_display_name("ms1", ms=ms, vitrine=vitrine) == "MS Name"
    assert resolve_product_display_name("only_v", ms=ms, vitrine=vitrine) == "Only Vitrine"


def test_sales_display_empty_when_both_missing() -> None:
    assert resolve_product_display_name("x", ms=None, vitrine=None) == ""


def test_build_display_map_ms_and_vitrine_only() -> None:
    ms = ParsedMsProductCatalog(
        by_code={
            "ms1": MsProductEntry("ms1", "MS Name", MsEntityKind.PRODUCT),
        },
        name_to_code={"MS Name": "ms1"},
    )
    vitrine = parse_product_catalog_sheet(
        [["id", "имя"], ["ms1", "Form Name"], ["only_v", "Only Vitrine"]],
    )
    result = build_product_display_name_map(ms=ms, vitrine=vitrine)
    assert result["ms1"] == "MS Name"
    assert result["only_v"] == "Only Vitrine"
    assert build_product_display_name_map(ms=None, vitrine=None) == {}


def test_build_display_map_ms_wins_on_casefold_collision() -> None:
    ms = ParsedMsProductCatalog(
        by_code={
            "C1": MsProductEntry("C1", "MS Name", MsEntityKind.PRODUCT),
        },
        name_to_code={"MS Name": "C1"},
    )
    vitrine = parse_product_catalog_sheet(
        [["id", "имя"], ["c1", "Form Name"]],
    )
    result = build_product_display_name_map(ms=ms, vitrine=vitrine)
    assert result["c1"] == "MS Name"
