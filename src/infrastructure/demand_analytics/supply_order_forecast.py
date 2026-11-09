from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.demand_analytics import (
    LONG_SHELF_TO_LIMIT_V1,
    SHORT_SHELF_LEAD_TIME_V1,
    DemandForecastEngine,
    ForecastPolicyNotRegistered,
    SalesHistoryReadFailed,
    VirtualStockReadFailed,
)

_LOGGER = logging.getLogger(__name__)

_POLICY_BY_CATEGORY: dict[Literal[2, 3], str] = {
    2: LONG_SHELF_TO_LIMIT_V1,
    3: SHORT_SHELF_LEAD_TIME_V1,
}


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketDemandForecastAdapter:
    """Order-port adapter. Cat 2/3 call named demand_analytics policies."""

    engine: DemandForecastEngine
    timezone: ZoneInfo

    @beartype
    def forecast_qty(
        self,
        *,
        machine_id: str,
        product_code: str,
        category: Literal[2, 3],
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
    ) -> Decimal | None:
        policy_key = _POLICY_BY_CATEGORY[category]
        result = self.engine.forecast(
            machine_id=machine_id,
            product_code=product_code,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            policy_key=policy_key,
            shelf_qty=shelf_qty,
            target_qty=target_qty,
            timezone=self.timezone,
        )
        extra = {
            "machine_id": machine_id,
            "product_code": product_code,
            "policy_key": policy_key,
        }
        if isinstance(result, ForecastPolicyNotRegistered):
            _LOGGER.info("demand_forecast_policy_missing", extra=extra)
            return None
        if result is None:
            _LOGGER.info("demand_forecast_unavailable", extra=extra)
            return None
        if isinstance(result, SalesHistoryReadFailed):
            _LOGGER.info("demand_forecast_sales_read_failed", extra=extra)
            return None
        if isinstance(result, VirtualStockReadFailed):
            _LOGGER.info("demand_forecast_stock_read_failed", extra=extra)
            return None
        _LOGGER.info("demand_forecast_qty", extra=extra)
        return result
