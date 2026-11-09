from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_sales_ingest_overlap_seconds_default_and_ge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KITVENDING_SALES_INGEST_OVERLAP_SECONDS", raising=False)
    from src.config.kitvending import KitVendingSettings

    settings = KitVendingSettings()
    assert settings.sales_ingest_overlap_seconds == 1800

    monkeypatch.setenv("KITVENDING_SALES_INGEST_OVERLAP_SECONDS", "-1")
    with pytest.raises(ValidationError):
        KitVendingSettings()

    monkeypatch.setenv("KITVENDING_SALES_INGEST_OVERLAP_SECONDS", "0")
    settings_zero = KitVendingSettings()
    assert settings_zero.sales_ingest_overlap_seconds == 0
