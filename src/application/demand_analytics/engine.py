from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.demand_analytics.ports import (
    DemandForecastPolicy,
    ForecastPolicyNotRegistered,
    SalesHistoryReadFailed,
    SkuSalesHistoryPort,
    VirtualStockReadFailed,
)


@beartype
class DemandForecastEngine:
    """Looks up a policy by key and calls it. A missing key does not read history."""

    def __init__(
        self,
        *,
        policies: Mapping[str, DemandForecastPolicy],
        history: SkuSalesHistoryPort,
    ) -> None:
        self._policies = dict(policies)
        self._history = history

    @beartype
    def forecast(
        self,
        *,
        machine_id: str,
        product_code: str,
        horizon_start: datetime,
        horizon_end: datetime,
        policy_key: str,
        shelf_qty: Decimal,
        target_qty: Decimal,
        timezone: ZoneInfo,
    ) -> (
        Decimal
        | None
        | ForecastPolicyNotRegistered
        | SalesHistoryReadFailed
        | VirtualStockReadFailed
    ):
        policy = self._policies.get(policy_key)
        if policy is None:
            return ForecastPolicyNotRegistered()
        return policy.forecast(
            machine_id=machine_id,
            product_code=product_code,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            shelf_qty=shelf_qty,
            target_qty=target_qty,
            timezone=timezone,
            history=self._history,
        )
