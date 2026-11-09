from __future__ import annotations

from src.config.mongodb import MongoSettings


def test_kitshop_mongo_collection_defaults() -> None:
    s = MongoSettings()
    assert s.kitshop_sales_backlog_collection == "kitshop_sales_backlog"
    assert s.kitshop_sales_ingest_cursors_collection == "kitshop_sales_ingest_cursors"
    assert s.kitshop_sale_receipts_collection == "kitshop_sale_receipts"


def test_kitshop_sale_receipts_collection_default() -> None:
    assert MongoSettings().kitshop_sale_receipts_collection == "kitshop_sale_receipts"
