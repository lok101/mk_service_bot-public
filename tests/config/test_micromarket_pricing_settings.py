from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.micromarket_pricing import MicromarketPricingSettings


def test_micromarket_pricing_defaults_load() -> None:
    """happy: defaults parse."""
    settings = MicromarketPricingSettings()
    assert settings.margin_percent_min <= settings.margin_percent_max
    assert settings.max_price_delta_pct == settings.max_price_delta_pct


def test_micromarket_pricing_rejects_inverted_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: min > max → ValidationError."""
    monkeypatch.setenv("MICROMARKET_MARGIN_PERCENT_MIN", "90")
    monkeypatch.setenv("MICROMARKET_MARGIN_PERCENT_MAX", "10")
    with pytest.raises(ValidationError):
        MicromarketPricingSettings()
