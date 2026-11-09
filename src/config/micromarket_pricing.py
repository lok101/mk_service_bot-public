from __future__ import annotations

from decimal import Decimal

from beartype import beartype
from pydantic import Field, model_validator

from src.config._base import ServiceSettingsBase


class MicromarketPricingSettings(ServiceSettingsBase):
    margin_percent_min: Decimal = Field(
        default=Decimal("20"),
        validation_alias="MICROMARKET_MARGIN_PERCENT_MIN",
    )
    margin_percent_max: Decimal = Field(
        default=Decimal("100"),
        validation_alias="MICROMARKET_MARGIN_PERCENT_MAX",
    )
    margin_floor_min: Decimal = Field(
        default=Decimal("20"),
        validation_alias="MICROMARKET_MARGIN_FLOOR_MIN",
    )
    margin_floor_max: Decimal = Field(
        default=Decimal("100"),
        validation_alias="MICROMARKET_MARGIN_FLOOR_MAX",
    )
    product_multiplier_min: Decimal = Field(
        default=Decimal("0.8"),
        validation_alias="MICROMARKET_PRODUCT_MULTIPLIER_MIN",
    )
    product_multiplier_max: Decimal = Field(
        default=Decimal("3.0"),
        validation_alias="MICROMARKET_PRODUCT_MULTIPLIER_MAX",
    )
    machine_multiplier_min: Decimal = Field(
        default=Decimal("0.8"),
        validation_alias="MICROMARKET_MACHINE_MULTIPLIER_MIN",
    )
    machine_multiplier_max: Decimal = Field(
        default=Decimal("3.0"),
        validation_alias="MICROMARKET_MACHINE_MULTIPLIER_MAX",
    )
    max_price_delta_pct: Decimal = Field(
        default=Decimal("15"),
        validation_alias="MICROMARKET_MAX_PRICE_DELTA_PCT",
    )

    @model_validator(mode="after")
    @beartype
    def _bounds_ordered(self) -> MicromarketPricingSettings:
        pairs = (
            ("MICROMARKET_MARGIN_PERCENT", self.margin_percent_min, self.margin_percent_max),
            ("MICROMARKET_MARGIN_FLOOR", self.margin_floor_min, self.margin_floor_max),
            (
                "MICROMARKET_PRODUCT_MULTIPLIER",
                self.product_multiplier_min,
                self.product_multiplier_max,
            ),
            (
                "MICROMARKET_MACHINE_MULTIPLIER",
                self.machine_multiplier_min,
                self.machine_multiplier_max,
            ),
        )
        for label, lo, hi in pairs:
            if lo > hi:
                raise ValueError(f"{label}_MIN must be <= {label}_MAX")
        return self
