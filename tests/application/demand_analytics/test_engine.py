from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.demand_analytics import (
    SHORT_SHELF_LEAD_TIME_V1,
    DemandForecastEngine,
    ForecastPolicyNotRegistered,
    SalesHistoryReadFailed,
)
from src.application.demand_analytics.ports import SkuSalesHistoryPort

_ZONE = ZoneInfo("Asia/Yekaterinburg")
_START = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
_END = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
_SHELF = Decimal("4")
_TARGET = Decimal("10")


class _History:
    def __init__(self) -> None:
        self.calls = 0

    def list_quantities(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
        sale_kind: str | None = None,
    ) -> tuple[tuple[datetime, Decimal], ...] | SalesHistoryReadFailed:
        self.calls += 1
        return ()


class _FixedPolicy:
    def __init__(self, result: Decimal | None) -> None:
        self._result = result
        self.seen: dict[str, object] | None = None

    def forecast(
        self,
        *,
        machine_id: str,
        product_code: str,
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
        timezone: ZoneInfo,
        history: SkuSalesHistoryPort,
    ) -> Decimal | None:
        listed = history.list_quantities(
            machine_id=machine_id,
            product_code=product_code,
            opened_at=horizon_start,
            closed_at=horizon_end,
            sale_kind=None,
        )
        self.seen = {
            "machine_id": machine_id,
            "product_code": product_code,
            "horizon_start": horizon_start,
            "horizon_end": horizon_end,
            "shelf_qty": shelf_qty,
            "target_qty": target_qty,
            "timezone": timezone,
            "listed": listed,
        }
        return self._result


def _engine(
    policies: dict[str, _FixedPolicy],
    history: _History,
) -> DemandForecastEngine:
    return DemandForecastEngine(policies=policies, history=history)


def test_registered_policy_returns_qty_and_sees_shelf_and_target() -> None:
    history = _History()
    policy = _FixedPolicy(Decimal("2"))
    result = _engine({SHORT_SHELF_LEAD_TIME_V1: policy}, history).forecast(
        machine_id="701",
        product_code="2311",
        horizon_start=_START,
        horizon_end=_END,
        policy_key=SHORT_SHELF_LEAD_TIME_V1,
        shelf_qty=_SHELF,
        target_qty=_TARGET,
        timezone=_ZONE,
    )
    assert result == Decimal("2")
    assert policy.seen == {
        "machine_id": "701",
        "product_code": "2311",
        "horizon_start": _START,
        "horizon_end": _END,
        "shelf_qty": _SHELF,
        "target_qty": _TARGET,
        "timezone": _ZONE,
        "listed": (),
    }
    assert history.calls == 1
    assert SHORT_SHELF_LEAD_TIME_V1 == "short_shelf_lead_time_v1"


def test_policy_none_is_unavailable() -> None:
    history = _History()
    policy = _FixedPolicy(None)
    result = _engine({SHORT_SHELF_LEAD_TIME_V1: policy}, history).forecast(
        machine_id="701",
        product_code="2311",
        horizon_start=_START,
        horizon_end=_END,
        policy_key=SHORT_SHELF_LEAD_TIME_V1,
        shelf_qty=_SHELF,
        target_qty=_TARGET,
        timezone=_ZONE,
    )
    assert result is None
    assert history.calls == 1


def test_missing_key_does_not_read_history() -> None:
    history = _History()
    result = _engine({}, history).forecast(
        machine_id="701",
        product_code="2311",
        horizon_start=_START,
        horizon_end=_END,
        policy_key=SHORT_SHELF_LEAD_TIME_V1,
        shelf_qty=_SHELF,
        target_qty=_TARGET,
        timezone=_ZONE,
    )
    assert isinstance(result, ForecastPolicyNotRegistered)
    assert history.calls == 0
