from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.infrastructure.composition.test_admin_http_deps_factory import (
    _minimal_runtime_with_master_data,
)

from src.application.demand_analytics import (
    LONG_SHELF_TO_LIMIT_V1,
    SHORT_SHELF_LEAD_TIME_V1,
    DemandForecastEngine,
    SalesHistoryReadFailed,
    VirtualStockReadFailed,
)
from src.application.micromarket_loading.supply_order_forecast import (
    AlwaysUnavailableSupplyOrderForecast,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.composition.factories.admin_http_deps import build_admin_http_deps
from src.infrastructure.demand_analytics.machine_sales_history import MachineSalesHistory
from src.infrastructure.demand_analytics.supply_order_forecast import (
    MicromarketDemandForecastAdapter,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_ZONE = ZoneInfo("Asia/Yekaterinburg")
_OPENED = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
_INSIDE = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
_OTHER_INSIDE = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
_OUTSIDE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)


def _sale(
    *,
    source_id: str,
    machine_id: str,
    product_code: str,
    quantity: str,
    occurred_at: datetime,
    sale_kind: str = "micromarket",
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=MachineId(machine_id),
        product_code=product_code,
        quantity=Decimal(quantity),
        occurred_at=occurred_at,
        ingested_at=_INGESTED,
        sale_kind=sale_kind,  # type: ignore[arg-type]
    )


class _BrokenSalesStore(InMemoryMachineSalesStore):
    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        raise RuntimeError("mongo down")


class _CountingPolicy:
    def __init__(self, result: Decimal | None | SalesHistoryReadFailed) -> None:
        self._result = result
        self.calls = 0

    def forecast(self, **_kwargs: object) -> Decimal | None | SalesHistoryReadFailed:
        self.calls += 1
        return self._result


class _ReadingPolicy:
    def forecast(
        self,
        *,
        machine_id: str,
        product_code: str,
        horizon_start: datetime,
        horizon_end: datetime,
        history: MachineSalesHistory,
        **_kwargs: object,
    ) -> Decimal | None | SalesHistoryReadFailed:
        return history.list_quantities(
            machine_id=machine_id,
            product_code=product_code,
            opened_at=horizon_start,
            closed_at=horizon_end,
            sale_kind="micromarket",
        )


def _adapter(
    policies: dict[str, object],
    history: MachineSalesHistory,
) -> MicromarketDemandForecastAdapter:
    return MicromarketDemandForecastAdapter(
        engine=DemandForecastEngine(policies=policies, history=history),  # type: ignore[arg-type]
        timezone=_ZONE,
    )


def _forecast(
    adapter: MicromarketDemandForecastAdapter,
    *,
    category: int,
) -> Decimal | None:
    return adapter.forecast_qty(
        machine_id="701",
        product_code="2311",
        category=category,  # type: ignore[arg-type]
        horizon_start=_OPENED,
        horizon_end=_CLOSED,
        shelf_qty=Decimal("2"),
        target_qty=Decimal("5"),
    )


def test_history_filters_sku_and_sale_kind() -> None:
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(
        _sale(
            source_id="a", machine_id="701", product_code="2311", quantity="2", occurred_at=_INSIDE
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="b",
            machine_id="701",
            product_code="2311",
            quantity="9",
            occurred_at=_OTHER_INSIDE,
            sale_kind="snack",
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="c", machine_id="701", product_code="9999", quantity="4", occurred_at=_INSIDE
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="d", machine_id="702", product_code="2311", quantity="7", occurred_at=_INSIDE
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="e",
            machine_id="701",
            product_code="2311",
            quantity="8",
            occurred_at=_OUTSIDE,
        ),
    )
    history = MachineSalesHistory(store)
    all_kinds = history.list_quantities(
        machine_id="701",
        product_code="2311",
        opened_at=_OPENED,
        closed_at=_CLOSED,
        sale_kind=None,
    )
    micromarket = history.list_quantities(
        machine_id="701",
        product_code="2311",
        opened_at=_OPENED,
        closed_at=_CLOSED,
        sale_kind="micromarket",
    )
    assert set(all_kinds) == {(_INSIDE, Decimal("2")), (_OTHER_INSIDE, Decimal("9"))}
    assert micromarket == ((_INSIDE, Decimal("2")),)


def test_history_store_error_is_read_failed() -> None:
    history = MachineSalesHistory(_BrokenSalesStore())
    result = history.list_quantities(
        machine_id="701",
        product_code="2311",
        opened_at=_OPENED,
        closed_at=_CLOSED,
        sale_kind=None,
    )
    assert isinstance(result, SalesHistoryReadFailed)


def test_category_two_calls_long_shelf_policy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = _CountingPolicy(Decimal("4"))
    history = MachineSalesHistory(InMemoryMachineSalesStore())
    adapter = _adapter({LONG_SHELF_TO_LIMIT_V1: policy}, history)
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=2)
    assert result == Decimal("4")
    assert policy.calls == 1
    assert any(record.getMessage() == "demand_forecast_qty" for record in caplog.records)
    qty_logs = [record for record in caplog.records if record.getMessage() == "demand_forecast_qty"]
    assert qty_logs[0].policy_key == LONG_SHELF_TO_LIMIT_V1  # type: ignore[attr-defined]


def test_category_two_missing_policy_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter({}, MachineSalesHistory(InMemoryMachineSalesStore()))
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=2)
    assert result is None
    missing = [
        record
        for record in caplog.records
        if record.getMessage() == "demand_forecast_policy_missing"
    ]
    assert len(missing) == 1
    assert missing[0].policy_key == LONG_SHELF_TO_LIMIT_V1  # type: ignore[attr-defined]


def test_empty_registry_returns_none_and_logs_missing_policy(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter({}, MachineSalesHistory(InMemoryMachineSalesStore()))
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=3)
    assert result is None
    missing = [
        record
        for record in caplog.records
        if record.getMessage() == "demand_forecast_policy_missing"
    ]
    assert len(missing) == 1
    assert missing[0].machine_id == "701"  # type: ignore[attr-defined]
    assert missing[0].product_code == "2311"  # type: ignore[attr-defined]
    assert missing[0].policy_key == SHORT_SHELF_LEAD_TIME_V1  # type: ignore[attr-defined]


def test_policy_none_logs_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    policy = _CountingPolicy(None)
    adapter = _adapter(
        {SHORT_SHELF_LEAD_TIME_V1: policy},
        MachineSalesHistory(InMemoryMachineSalesStore()),
    )
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=3)
    assert result is None
    assert policy.calls == 1
    assert any(record.getMessage() == "demand_forecast_unavailable" for record in caplog.records)


def test_sales_read_failure_returns_none_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter(
        {SHORT_SHELF_LEAD_TIME_V1: _ReadingPolicy()},
        MachineSalesHistory(_BrokenSalesStore()),
    )
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=3)
    assert result is None
    assert any(
        record.getMessage() == "demand_forecast_sales_read_failed" for record in caplog.records
    )


def test_decimal_policy_is_returned(caplog: pytest.LogCaptureFixture) -> None:
    adapter = _adapter(
        {SHORT_SHELF_LEAD_TIME_V1: _CountingPolicy(Decimal("6"))},
        MachineSalesHistory(InMemoryMachineSalesStore()),
    )
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=3)
    assert result == Decimal("6")
    assert any(record.getMessage() == "demand_forecast_qty" for record in caplog.records)


def test_stock_read_failure_returns_none_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _StockFailPolicy:
        def forecast(self, **_kwargs: object) -> VirtualStockReadFailed:
            return VirtualStockReadFailed()

    adapter = _adapter(
        {SHORT_SHELF_LEAD_TIME_V1: _StockFailPolicy()},
        MachineSalesHistory(InMemoryMachineSalesStore()),
    )
    with caplog.at_level(logging.INFO):
        result = _forecast(adapter, category=3)
    assert result is None
    assert any(
        record.getMessage() == "demand_forecast_stock_read_failed" for record in caplog.records
    )


def test_admin_http_deps_wires_both_shelf_policies(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime, settings = _minimal_runtime_with_master_data(monkeypatch)
    deps = build_admin_http_deps(runtime, settings)
    forecast = deps.supply_order_demand_forecast
    assert isinstance(forecast, MicromarketDemandForecastAdapter)
    assert not isinstance(forecast, AlwaysUnavailableSupplyOrderForecast)
    assert forecast.timezone == deps.timezone
    with caplog.at_level(logging.INFO):
        cat3 = forecast.forecast_qty(
            machine_id="701",
            product_code="2311",
            category=3,
            horizon_start=_OPENED,
            horizon_end=_CLOSED,
            shelf_qty=Decimal("1"),
            target_qty=Decimal("2"),
        )
        cat2 = forecast.forecast_qty(
            machine_id="701",
            product_code="2311",
            category=2,
            horizon_start=_OPENED,
            horizon_end=_CLOSED,
            shelf_qty=Decimal("1"),
            target_qty=Decimal("2"),
        )
    # Empty sales + empty stock → T+=0 → unavailable (both policies registered)
    assert cat3 is None
    assert cat2 is None
    unavailable = [
        record for record in caplog.records if record.getMessage() == "demand_forecast_unavailable"
    ]
    assert len(unavailable) == 2
    keys = {record.policy_key for record in unavailable}  # type: ignore[attr-defined]
    assert keys == {SHORT_SHELF_LEAD_TIME_V1, LONG_SHELF_TO_LIMIT_V1}
    assert not any(
        record.getMessage() == "demand_forecast_policy_missing" for record in caplog.records
    )
