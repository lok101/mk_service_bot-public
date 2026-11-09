from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from src.infrastructure.snack_loading.ms_loading import available_from_stock_bystore_rows

_STORE = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_PRODUCT = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_CODE = "SKU1"


def _store_href(store_id: UUID) -> str:
    return f"https://api.moysklad.ru/api/remap/1.2/entity/store/{store_id}"


def _product_href(product_id: UUID) -> str:
    return f"https://api.moysklad.ru/api/remap/1.2/entity/product/{product_id}"


def test_main_stock_reader_parses_stock_by_store_qty_and_product_code() -> None:
    rows = [
        {
            "meta": {
                "href": _product_href(_PRODUCT),
                "type": "product",
            },
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_STORE), "type": "store"},
                    "name": "Main",
                    "stock": 12.0,
                }
            ],
        }
    ]
    available = available_from_stock_bystore_rows(
        rows,
        store_id=_STORE,
        product_id_to_code={_PRODUCT: _CODE},
    )
    assert available == {_CODE: Decimal("12")}


def test_main_stock_reader_matches_stock_row_code_when_meta_id_unknown() -> None:
    variant_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    rows = [
        {
            "meta": {
                "href": f"https://api.moysklad.ru/api/remap/1.2/entity/variant/{variant_id}",
                "type": "variant",
            },
            "code": _CODE,
            "stockByStore": [
                {
                    "meta": {"href": _store_href(_STORE), "type": "store"},
                    "name": "Main",
                    "stock": 4.0,
                }
            ],
        }
    ]
    available = available_from_stock_bystore_rows(
        rows,
        store_id=_STORE,
        product_id_to_code={},
        catalog_codes={_CODE},
    )
    assert available == {_CODE: Decimal("4")}


def test_main_stock_reader_ignores_top_level_stock_without_stock_by_store() -> None:
    rows = [
        {
            "meta": {"href": _product_href(_PRODUCT), "type": "product", "code": "WRONG"},
            "stock": 99.0,
            "code": "WRONG",
        }
    ]
    available = available_from_stock_bystore_rows(
        rows,
        store_id=_STORE,
        product_id_to_code={_PRODUCT: _CODE},
    )
    assert available == {}
