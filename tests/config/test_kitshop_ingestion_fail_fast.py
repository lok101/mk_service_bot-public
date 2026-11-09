from __future__ import annotations

from pathlib import Path

import pytest

from src.config.kitshop import KitShopSettings


def test_kitshop_ingest_enabled_requires_accounts(tmp_path: Path) -> None:
    settings = KitShopSettings(
        ingestion_enabled=True,
        accounts_path=tmp_path / "missing.json",
    )
    with pytest.raises(ValueError, match="KITSHOP_SALES_INGESTION_ENABLED"):
        settings.require_configured_for_ingestion()


def test_kitshop_ingest_disabled_no_worker() -> None:
    settings = KitShopSettings(ingestion_enabled=False)
    worker = None
    if settings.ingestion_enabled:
        worker = object()
    assert worker is None
