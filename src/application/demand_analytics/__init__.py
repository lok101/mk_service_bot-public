from __future__ import annotations

from src.application.demand_analytics.engine import DemandForecastEngine
from src.application.demand_analytics.long_shelf_to_limit import LongShelfToLimitV1Policy
from src.application.demand_analytics.ports import (
    DemandForecastPolicy,
    ForecastPolicyNotRegistered,
    SalesHistoryReadFailed,
    SkuSalesHistoryPort,
    SkuVirtualStockHistoryPort,
    VirtualStockReadFailed,
)
from src.application.demand_analytics.short_shelf_lead_time import (
    LOOKBACK_CALENDAR_DAYS,
    ShortShelfLeadTimeV1Policy,
)

LONG_SHELF_TO_LIMIT_V1 = "long_shelf_to_limit_v1"
SHORT_SHELF_LEAD_TIME_V1 = "short_shelf_lead_time_v1"

__all__ = [
    "LOOKBACK_CALENDAR_DAYS",
    "LONG_SHELF_TO_LIMIT_V1",
    "SHORT_SHELF_LEAD_TIME_V1",
    "DemandForecastEngine",
    "DemandForecastPolicy",
    "ForecastPolicyNotRegistered",
    "LongShelfToLimitV1Policy",
    "SalesHistoryReadFailed",
    "ShortShelfLeadTimeV1Policy",
    "SkuSalesHistoryPort",
    "SkuVirtualStockHistoryPort",
    "VirtualStockReadFailed",
]
