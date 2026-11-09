from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.application.inventory_reconciliation.sellable_fakes import (
    MappingSellableProductCodeCatalog,
)

from src.application.form_submissions import NonRetryableOutboxError
from src.application.inventory_reconciliation.create_daily_sales_demands import (
    CreateDailySalesDemands,
    DailySalesDemandTransientError,
    IngestCursorNotReady,
    SellableCatalogNotReady,
    UnresolvedSellableCodesError,
    UnresolvedStoreCodesError,
    price_to_kop,
)
from src.application.inventory_reconciliation.ms_registrar_ports import (
    RegistrarPermanentError,
    RegistrarTransientError,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

TZ = ZoneInfo("Europe/Moscow")
SNACK_CH = UUID("11111111-1111-1111-1111-111111111111")
PROJECT = UUID("33333333-3333-3333-3333-333333333333")


@dataclass
class FakeDailyRegistrar:
    calls: list[dict] = field(default_factory=list)
    attempted: list[str] = field(default_factory=list)
    fail_codes: set[str] = field(default_factory=set)
    permanent_fail_codes: set[str] = field(default_factory=set)
    transient_fail_codes: set[str] = field(default_factory=set)

    async def register_daily_sales_demand(self, **kwargs):  # type: ignore[no-untyped-def]
        code = kwargs["warehouse_code"]
        self.attempted.append(code)
        if code in self.permanent_fail_codes:
            raise RegistrarPermanentError(f"store not found: {code}")
        if code in self.transient_fail_codes:
            raise RegistrarTransientError(f"ms transient {code}")
        if code in self.fail_codes:
            raise RuntimeError(f"ms transient {code}")
        self.calls.append(kwargs)


def _sale(
    *,
    source_id: str,
    machine_code: str,
    kind: str,
    product: str,
    price: Decimal | None,
    at: datetime,
    qty: str = "1",
) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=MachineId(machine_code),
        product_code=product,
        quantity=Decimal(qty),
        occurred_at=at,
        ingested_at=at,
        sale_kind=kind,  # type: ignore[arg-type]
        machine_code=machine_code,
        price=price,
    )


def _uc(
    store: InMemoryMachineSalesStore,
    registrar: FakeDailyRegistrar,
    *,
    catalog: MappingSellableProductCodeCatalog,
) -> CreateDailySalesDemands:
    return CreateDailySalesDemands(
        sales_store=store,
        registrar=registrar,
        sellable_catalog=catalog,
        display_timezone="Europe/Moscow",
        project_id=PROJECT,
        snack_sales_channel_id=SNACK_CH,
    )


def test_unmapped_registrar_error_fails_fast() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="S_A",
            kind="snack",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=10),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="b",
            machine_code="S_B",
            kind="snack",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar(fail_codes={"S_A"})
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with pytest.raises(RuntimeError, match="ms transient S_A"):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.attempted == ["S_A"]
    assert registrar.calls == []


def test_coffee_only_day_skips_without_registrar_calls() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="c1",
            machine_code="C1",
            kind="coffee",
            product="P2",
            price=Decimal("50.00"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P2"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.calls == []


def test_micromarket_only_day_skips_without_registrar_calls() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="m1",
            machine_code="M1",
            kind="micromarket",
            product="P3",
            price=Decimal("10.00"),
            at=day_start.replace(hour=12),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P3"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.calls == []


def test_snack_day_creates_demand_with_snack_channel() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="s1",
            machine_code="S1",
            kind="snack",
            product="P1",
            price=Decimal("100.00"),
            at=day_start.replace(hour=10),
            qty="2",
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert len(registrar.calls) == 1
    assert registrar.calls[0]["warehouse_code"] == "S1"
    assert registrar.calls[0]["sales_channel_id"] == SNACK_CH


def test_create_daily_demands_happy_with_sellable_membership() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="s1",
            machine_code="S1",
            kind="snack",
            product="P1",
            price=Decimal("100.00"),
            at=day_start.replace(hour=10),
            qty="2",
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert len(registrar.calls) == 1
    assert registrar.calls[0]["warehouse_code"] == "S1"


def test_store_miss_skips_bad_machine_creates_valid_then_terminal() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="ok",
            machine_code="S_OK",
            kind="snack",
            product="P1",
            price=Decimal("50"),
            at=day_start.replace(hour=10),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="bad",
            machine_code="S_BAD",
            kind="snack",
            product="P1",
            price=Decimal("50"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar(permanent_fail_codes={"S_BAD"})
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with pytest.raises(UnresolvedStoreCodesError) as exc_info:
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert "S_BAD" in str(exc_info.value)
    assert {c["warehouse_code"] for c in registrar.calls} == {"S_OK"}


def test_collect_all_partial_create_then_terminal() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="clean",
            machine_code="S_CLEAN",
            kind="snack",
            product="P_OK",
            price=Decimal("50"),
            at=day_start.replace(hour=11),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="miss1",
            machine_code="S_MISS1",
            kind="snack",
            product="UNKNOWN_A",
            price=Decimal("50"),
            at=day_start.replace(hour=12),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="miss2",
            machine_code="S_MISS2",
            kind="snack",
            product="UNKNOWN_B",
            price=Decimal("50"),
            at=day_start.replace(hour=13),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P_OK"}))
    with pytest.raises(UnresolvedSellableCodesError) as excinfo:
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert len(registrar.calls) == 1
    assert registrar.calls[0]["warehouse_code"] == "S_CLEAN"
    unresolved = excinfo.value.unresolved
    assert ("S_MISS1", "UNKNOWN_A") in unresolved
    assert ("S_MISS2", "UNKNOWN_B") in unresolved
    assert len(unresolved) == 2


def test_snack_miss_terminal_coffee_skipped() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="sn",
            machine_code="SN1",
            kind="snack",
            product="MISS_SNACK",
            price=Decimal("10"),
            at=day_start.replace(hour=10),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="cf",
            machine_code="CF1",
            kind="coffee",
            product="MISS_COFFEE",
            price=Decimal("20"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset())  # ready but empty codes
    with pytest.raises(UnresolvedSellableCodesError) as excinfo:
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.calls == []
    assert ("SN1", "MISS_SNACK") in excinfo.value.unresolved
    assert ("CF1", "MISS_COFFEE") not in excinfo.value.unresolved
    assert len(excinfo.value.unresolved) == 1


def test_empty_sellable_catalog_raises_retryable() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="s1",
            machine_code="S1",
            kind="snack",
            product="P1",
            price=Decimal("1"),
            at=datetime(2026, 8, 9, 10, 0, tzinfo=TZ),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}), _ready=False)
    with pytest.raises(SellableCatalogNotReady):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.calls == []


def test_create_daily_demands_happy_two_machines() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    store.insert_if_absent(
        _sale(
            source_id="s1",
            machine_code="S1",
            kind="snack",
            product="P1",
            price=Decimal("100.00"),
            at=day_start.replace(hour=10),
            qty="2",
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="c1",
            machine_code="C1",
            kind="coffee",
            product="P2",
            price=Decimal("50.00"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1", "P2"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert len(registrar.calls) == 1
    assert registrar.calls[0]["warehouse_code"] == "S1"
    assert registrar.calls[0]["sales_channel_id"] == SNACK_CH
    assert registrar.calls[0]["moment"] == datetime(2026, 8, 9, 23, 55, tzinfo=TZ)
    assert "C1" not in {c["warehouse_code"] for c in registrar.calls}


def test_cursor_gate_raises_retryable() -> None:
    store = InMemoryMachineSalesStore()
    # cursor None
    uc = _uc(
        store,
        FakeDailyRegistrar(),
        catalog=MappingSellableProductCodeCatalog(codes=frozenset()),
    )
    with pytest.raises(IngestCursorNotReady):
        asyncio.run(uc.execute(sales_day=date(2026, 8, 9)))


def test_cursor_gate_exact_day_end_allows() -> None:
    """edge: cursor == day_end passes readiness gate."""
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end)
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset())
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.calls == []


def test_cursor_gate_one_second_before_day_end_raises() -> None:
    """edge: cursor just before day_end stays not ready."""
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_end = datetime(2026, 8, 10, 0, 0, tzinfo=TZ)
    store.save_global_cursor(day_end - timedelta(seconds=1))
    uc = _uc(
        store,
        FakeDailyRegistrar(),
        catalog=MappingSellableProductCodeCatalog(codes=frozenset()),
    )
    with pytest.raises(IngestCursorNotReady):
        asyncio.run(uc.execute(sales_day=day))


def test_empty_day_success() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset())
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert registrar.calls == []


def test_price_none_excludes_line() -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="snack",
            product="P1",
            price=None,
            at=day_start.replace(hour=1),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="b",
            machine_code="M1",
            kind="snack",
            product="P1",
            price=Decimal("10.00"),
            at=day_start.replace(hour=2),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert len(registrar.calls) == 1
    assert len(registrar.calls[0]["lines"]) == 1
    assert registrar.calls[0]["lines"][0].price_kop == 1000


def test_mixed_kind_skips_machine() -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="snack",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=1),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="b",
            machine_code="M1",
            kind="coffee",
            product="P2",
            price=Decimal("1"),
            at=day_start.replace(hour=2),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1", "P2"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert registrar.calls == []


def test_unknown_kind_skips_machine() -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="unknown",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=1),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert registrar.calls == []


@pytest.mark.parametrize(
    ("kind", "message"),
    (
        ("coffee", "daily_sales_demand skip machine: non_snack_sale_kind"),
        ("micromarket", "daily_sales_demand skip machine: non_snack_sale_kind"),
    ),
)
def test_expected_non_snack_kind_logs_info_not_error(
    kind: str,
    message: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind=kind,
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=1),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with caplog.at_level(logging.INFO):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    skip_records = [record for record in caplog.records if record.getMessage() == message]
    assert len(skip_records) == 1
    assert skip_records[0].levelno == logging.INFO
    assert skip_records[0].sale_kinds == [kind]
    assert not any(
        record.getMessage() == "daily_sales_demand skip machine: invalid sale_kind"
        for record in caplog.records
    )
    assert registrar.calls == []


def test_unknown_kind_skip_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="unknown",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=1),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with caplog.at_level(logging.INFO):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    skip_records = [
        record
        for record in caplog.records
        if record.getMessage() == "daily_sales_demand skip machine: invalid sale_kind"
    ]
    assert len(skip_records) == 1
    assert skip_records[0].levelno == logging.ERROR
    assert skip_records[0].sale_kinds == ["unknown"]
    assert registrar.calls == []


def test_mixed_kind_skip_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="snack",
            product="P1",
            price=Decimal("1"),
            at=day_start.replace(hour=1),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="b",
            machine_code="M1",
            kind="coffee",
            product="P2",
            price=Decimal("2"),
            at=day_start.replace(hour=2),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1", "P2"}))
    with caplog.at_level(logging.INFO):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    skip_records = [
        record
        for record in caplog.records
        if record.getMessage() == "daily_sales_demand skip machine: invalid sale_kind"
    ]
    assert len(skip_records) == 1
    assert skip_records[0].levelno == logging.ERROR
    assert skip_records[0].sale_kinds == ["coffee", "snack"]
    assert registrar.calls == []


def test_zero_positions_after_price_filter_skips() -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="a",
            machine_code="M1",
            kind="snack",
            product="P1",
            price=None,
            at=day_start.replace(hour=1),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert registrar.calls == []


def test_transient_ms_continues_then_retryable_tail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    for code, hour, source in (("S_A", 10, "a"), ("S_MID", 11, "b"), ("S_C", 12, "c")):
        store.insert_if_absent(
            _sale(
                source_id=source,
                machine_code=code,
                kind="snack",
                product="P1",
                price=Decimal("1"),
                at=day_start.replace(hour=hour),
            ),
        )
    registrar = FakeDailyRegistrar(transient_fail_codes={"S_MID"})
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(DailySalesDemandTransientError) as exc_info,
    ):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert registrar.attempted == ["S_A", "S_MID", "S_C"]
    assert {c["warehouse_code"] for c in registrar.calls} == {"S_A", "S_C"}
    assert exc_info.value.warehouse_codes == frozenset({"S_MID"})
    assert "S_MID" in str(exc_info.value)
    assert not isinstance(exc_info.value, NonRetryableOutboxError)
    tail_records = [
        record
        for record in caplog.records
        if record.getMessage() == "daily_sales_demand transient tail"
    ]
    assert len(tail_records) == 1
    tail = tail_records[0]
    assert tail.levelno == logging.WARNING
    assert tail.transient_warehouse_codes == ["S_MID"]
    assert tail.sales_day == "2026-08-09"
    assert not any(record.levelno >= logging.ERROR for record in caplog.records)


def test_transients_before_unresolved_sellable() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="ok",
            machine_code="S_OK",
            kind="snack",
            product="P_OK",
            price=Decimal("50"),
            at=day_start.replace(hour=10),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="mid",
            machine_code="S_MID",
            kind="snack",
            product="P_OK",
            price=Decimal("50"),
            at=day_start.replace(hour=11),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="dirty",
            machine_code="S_DIRTY",
            kind="snack",
            product="UNKNOWN",
            price=Decimal("50"),
            at=day_start.replace(hour=12),
        ),
    )
    registrar = FakeDailyRegistrar(transient_fail_codes={"S_MID"})
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P_OK"}))
    with pytest.raises(DailySalesDemandTransientError) as exc_info:
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert exc_info.value.warehouse_codes == frozenset({"S_MID"})
    assert "S_DIRTY" not in registrar.attempted
    assert {c["warehouse_code"] for c in registrar.calls} == {"S_OK"}


def test_transients_before_unresolved_store() -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="ok",
            machine_code="S_OK",
            kind="snack",
            product="P1",
            price=Decimal("50"),
            at=day_start.replace(hour=10),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="mid",
            machine_code="S_MID",
            kind="snack",
            product="P1",
            price=Decimal("50"),
            at=day_start.replace(hour=11),
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="perm",
            machine_code="S_PERM",
            kind="snack",
            product="P1",
            price=Decimal("50"),
            at=day_start.replace(hour=12),
        ),
    )
    registrar = FakeDailyRegistrar(
        transient_fail_codes={"S_MID"},
        permanent_fail_codes={"S_PERM"},
    )
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    with pytest.raises(DailySalesDemandTransientError) as exc_info:
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert exc_info.value.warehouse_codes == frozenset({"S_MID"})
    assert registrar.attempted == ["S_OK", "S_MID", "S_PERM"]
    assert {c["warehouse_code"] for c in registrar.calls} == {"S_OK"}


def test_full_success_logs_candidate_counts(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryMachineSalesStore()
    day = date(2026, 8, 9)
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    store.insert_if_absent(
        _sale(
            source_id="s1",
            machine_code="S1",
            kind="snack",
            product="P1",
            price=Decimal("100.00"),
            at=day_start.replace(hour=10),
            qty="2",
        ),
    )
    store.insert_if_absent(
        _sale(
            source_id="c1",
            machine_code="C1",
            kind="coffee",
            product="P2",
            price=Decimal("50.00"),
            at=day_start.replace(hour=11),
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1", "P2"}))
    with caplog.at_level(logging.INFO):
        asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=day))
    assert len(registrar.calls) == 1
    assert registrar.calls[0]["warehouse_code"] == "S1"
    assert "daily_sales_demand completed" in caplog.text


def test_missing_machine_code_falls_back_to_machine_id() -> None:
    store = InMemoryMachineSalesStore()
    day_start = datetime(2026, 8, 9, 0, 0, tzinfo=TZ)
    store.save_global_cursor(datetime(2026, 8, 10, 0, 0, tzinfo=TZ))
    sale = _sale(
        source_id="a",
        machine_code="MID",
        kind="snack",
        product="P1",
        price=Decimal("1"),
        at=day_start.replace(hour=1),
    )
    store.insert_if_absent(
        MachineSale(
            source_id=sale.source_id,
            machine_id=MachineId("MID"),
            product_code=sale.product_code,
            quantity=sale.quantity,
            occurred_at=sale.occurred_at,
            ingested_at=sale.ingested_at,
            sale_kind="snack",
            machine_code=None,
            price=sale.price,
        ),
    )
    registrar = FakeDailyRegistrar()
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}))
    asyncio.run(_uc(store, registrar, catalog=catalog).execute(sales_day=date(2026, 8, 9)))
    assert registrar.calls[0]["warehouse_code"] == "MID"


def test_price_to_kop_rounds_to_int() -> None:
    assert price_to_kop(Decimal("10.50")) == 1050
    assert price_to_kop(Decimal("10.505")) == 1051  # HALF_UP
    _ = ROUND_HALF_UP
