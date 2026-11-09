from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.application.inventory_reconciliation.backfill_sale_prices import (
    PRICE_BACKFILL_CUTOVER,
    BackfillSalePricesFromKit,
)
from src.application.inventory_reconciliation.kitvending import KitSalePriceRow
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_MACHINE_ID = MachineId("vm-01")
_INGESTED = datetime(2026, 6, 8, 11, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FakeKitPriceFetcher:
    rows: tuple[KitSalePriceRow, ...]
    calls: list[tuple[datetime, datetime]] = field(default_factory=list)

    def fetch_price_rows(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> tuple[KitSalePriceRow, ...]:
        self.calls.append((from_date, to_date))
        return self.rows


def _sale(
    *,
    source_id: str,
    occurred_at: datetime,
    price: Decimal | None = None,
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=_MACHINE_ID,
        product_code="coffee-1",
        quantity=Decimal("1"),
        occurred_at=occurred_at,
        ingested_at=_INGESTED,
        price=price,
    )


@dataclass(slots=True)
class _RaceConditionMachineSalesStore(InMemoryMachineSalesStore):
    """Подкласс `InMemoryMachineSalesStore`: window-снимок «устарел» — doc уже получил price.

    Реальное наследование (не `__getattr__`-делегирование) нужно, чтобы
    `@beartype`-Protocol `isinstance` на границе `BackfillSalePricesFromKit` проходил:
    начиная с Python 3.12 `typing.Protocol.__instancecheck__` использует
    `inspect.getattr_static`, который не триггерит `__getattr__` на инстансе —
    структурный fake-wrapper через `__getattr__` не распознаётся как `MachineSalesStore`.
    """

    stale_sale: MachineSale = field(kw_only=True)

    def min_occurred_at_missing_price(self) -> datetime | None:
        return self.stale_sale.occurred_at

    def find_missing_price_before(self, before: datetime) -> tuple[MachineSale, ...]:
        return (self.stale_sale,)


def test_execute_returns_zero_counters_when_no_missing_price_docs() -> None:
    # edge: пустое окно — success, без обращения к Kit
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="p-1", occurred_at=_INGESTED, price=Decimal("1.00")))
    fetcher = _FakeKitPriceFetcher(rows=())
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.window_from is None
    assert result.window_to == PRICE_BACKFILL_CUTOVER
    assert result.updated == 0
    assert result.already_priced_skipped == 0
    assert result.missing_in_kit == 0
    assert result.missing_sum == 0
    assert result.invalid_sum == 0
    assert fetcher.calls == []


def test_execute_updates_docs_with_matching_kit_price() -> None:
    # happy: docs без price получают price из Kit map
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="s-1", occurred_at=since))
    fetcher = _FakeKitPriceFetcher(rows=(KitSalePriceRow(source_id="s-1", sum_value=45.5),))
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.updated == 1
    assert result.window_from == since
    assert fetcher.calls == [(since, PRICE_BACKFILL_CUTOVER)]
    loaded = store.find_missing_price_before(PRICE_BACKFILL_CUTOVER)
    assert loaded == ()


def test_execute_skips_already_priced_docs_via_already_priced_skipped_counter() -> None:
    # idempotency: doc был без price в снимке окна, но уже получил price к моменту apply
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    stale_snapshot = _sale(source_id="s-1", occurred_at=since)  # price=None — устаревший снимок
    store = _RaceConditionMachineSalesStore(stale_sale=stale_snapshot)
    store.insert_if_absent(_sale(source_id="s-1", occurred_at=since, price=Decimal("99.00")))
    fetcher = _FakeKitPriceFetcher(rows=(KitSalePriceRow(source_id="s-1", sum_value=45.5),))
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.updated == 0
    assert result.already_priced_skipped == 1


def test_execute_counts_missing_in_kit_when_source_id_not_in_map() -> None:
    # error: doc без price, но Kit не вернул такой source_id
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="s-1", occurred_at=since))
    fetcher = _FakeKitPriceFetcher(rows=())
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.updated == 0
    assert result.missing_in_kit == 1


def test_execute_counts_missing_sum_when_row_has_no_sum_value() -> None:
    # error: Kit вернул source_id, но без Sum
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="s-1", occurred_at=since))
    fetcher = _FakeKitPriceFetcher(rows=(KitSalePriceRow(source_id="s-1", sum_value=None),))
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.updated == 0
    assert result.missing_sum == 1
    assert result.missing_in_kit == 0


def test_backfill_sale_prices_missing_sum_not_double_counted_as_missing_in_kit() -> None:
    # invariant: row без Sum → только missing_sum; absent-in-kit → только missing_in_kit
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="no-sum", occurred_at=since))
    store.insert_if_absent(_sale(source_id="absent-in-kit", occurred_at=since))
    fetcher = _FakeKitPriceFetcher(
        rows=(KitSalePriceRow(source_id="no-sum", sum_value=None),),
    )
    result = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher).execute()
    assert result.missing_sum == 1
    assert result.missing_in_kit == 1  # только absent-in-kit, НЕ no-sum
    assert result.updated == 0


def test_execute_counts_invalid_sum_when_value_not_finite() -> None:
    # error: Sum есть, но не парсится в конечный Decimal
    since = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    store = InMemoryMachineSalesStore()
    store.insert_if_absent(_sale(source_id="s-1", occurred_at=since))
    fetcher = _FakeKitPriceFetcher(rows=(KitSalePriceRow(source_id="s-1", sum_value=float("nan")),))
    use_case = BackfillSalePricesFromKit(sales_store=store, price_fetcher=fetcher)

    result = use_case.execute()

    assert result.updated == 0
    assert result.invalid_sum == 1
    assert result.missing_in_kit == 1
