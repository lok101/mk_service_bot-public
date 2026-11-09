from __future__ import annotations

from pydantic import Field

from src.config._base import ServiceSettingsBase


class DomainProductIdentitySettings(ServiceSettingsBase):
    enabled: bool = Field(
        default=False,
        validation_alias="DOMAIN_PRODUCT_IDENTITY_ENABLED",
    )
    collection: str = Field(
        default="domain_products",
        validation_alias="MONGODB_DOMAIN_PRODUCTS_COLLECTION",
        min_length=1,
    )
    border_registration_collection: str = Field(
        default="border_registrations",
        validation_alias="MONGODB_BORDER_REGISTRATIONS_COLLECTION",
        min_length=1,
    )
