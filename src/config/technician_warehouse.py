from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, Field
from pydantic_settings import NoDecode

from src.config._base import ServiceSettingsBase


def _parse_codes(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    raw = value.split(",") if isinstance(value, str) else value
    return tuple(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))


SupplyStoreCodes = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_parse_codes)]


class TechnicianWarehouseSettings(ServiceSettingsBase):
    supply_store_codes: SupplyStoreCodes = Field(
        default=(),
        validation_alias="TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES",
    )
    ms_lookback_days: int = Field(
        default=60,
        validation_alias="TECHNICIAN_WAREHOUSE_MS_LOOKBACK_DAYS",
        ge=0,
        le=90,
    )
