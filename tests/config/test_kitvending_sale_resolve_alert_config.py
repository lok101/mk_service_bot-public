from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_sale_resolve_alert_cooldown_default_and_ge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KITVENDING_SALE_RESOLVE_ALERT_COOLDOWN_MINUTES", raising=False)
    from src.config.kitvending import KitVendingSettings

    s = KitVendingSettings()
    assert s.sale_resolve_alert_cooldown_minutes == 60

    monkeypatch.setenv("KITVENDING_SALE_RESOLVE_ALERT_COOLDOWN_MINUTES", "0")
    with pytest.raises(ValidationError):
        KitVendingSettings()
