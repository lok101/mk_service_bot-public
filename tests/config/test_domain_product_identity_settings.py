from __future__ import annotations

from src.config.domain_product_identity import DomainProductIdentitySettings


def test_domain_product_identity_disabled_by_default() -> None:
    settings = DomainProductIdentitySettings()
    assert settings.enabled is False
    assert settings.collection == "domain_products"


def test_settings_nests_domain_product_identity() -> None:
    from src.config.settings import Settings

    assert "domain_product_identity" in Settings.model_fields
