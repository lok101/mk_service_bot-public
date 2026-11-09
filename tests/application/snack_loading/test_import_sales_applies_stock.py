from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.snack_loading.apply_sale import ApplySnackSaleToStock
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.domain.snack_loading import SnackMachineStock
from src.infrastructure.testing.kitvending_stubs import StubKitVendingClient
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore
from src.infrastructure.testing.snack_loading_fakes import (
    InMemoryKitMatrixDeployMapStore,
    InMemorySnackMachineStockStore,
)


@dataclass(slots=True)
class _RecordingUnresolvedAlertNotifier:
    alerts: list[int] = field(default_factory=list)

    def notify_unresolved_sales(self, *, count: int) -> None:
        self.alerts.append(count)


def _unresolved_snack_rows(count: int) -> list[dict[str, str]]:
    return [
        {
            "source_id": f"kv-unresolved-{index}",
            "vending_machine_code": "514",
            "product_code": "SKU1",
            "quantity": "1",
            "occurred_at": "2026-07-02T12:00:00Z",
            "sale_kind": "snack",
            "kit_matrix_id": "99",
            "kit_vending_machine_id": "7",
            "kit_line_number": "1",
        }
        for index in range(count)
    ]


def test_import_kit_vending_sales_applies_snack_stock() -> None:
    sales_store = InMemoryMachineSalesStore()
    stock_store = InMemorySnackMachineStockStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)

    client = StubKitVendingClient(
        rows=[
            {
                "source_id": "kv-snack-1",
                "vending_machine_code": "514",
                "product_code": "SKU1",
                "quantity": "1",
                "occurred_at": "2026-07-02T12:00:00Z",
                "sale_kind": "snack",
                "kit_matrix_id": "42",
                "kit_vending_machine_id": "7",
                "kit_line_number": "1",
            },
        ],
    )
    apply = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "SKU1",
    )
    service = ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=client,
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=apply,
    )

    result = service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    assert result.inserted == 1
    loaded = stock_store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "SnackA", 1) == Decimal("4")


def test_import_skips_apply_snack_sale_when_not_inserted(monkeypatch: pytest.MonkeyPatch) -> None:
    sales_store = InMemoryMachineSalesStore()
    stock_store = InMemorySnackMachineStockStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)

    row = {
        "source_id": "kv-snack-1",
        "vending_machine_code": "514",
        "product_code": "SKU1",
        "quantity": "1",
        "occurred_at": "2026-07-02T12:00:00Z",
        "sale_kind": "snack",
        "kit_matrix_id": "42",
        "kit_vending_machine_id": "7",
        "kit_line_number": "1",
    }
    apply = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **_: "SKU1",
    )
    calls: list[MachineSale] = []
    real_execute = ApplySnackSaleToStock.execute

    def _spy(self: ApplySnackSaleToStock, sale: MachineSale) -> MachineSale:
        calls.append(sale)
        return real_execute(self, sale)

    monkeypatch.setattr(ApplySnackSaleToStock, "execute", _spy)
    service = ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=StubKitVendingClient(rows=[row]),
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=apply,
    )

    first = service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))
    second = service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    assert first.inserted == 1
    assert second.inserted == 0
    assert len(calls) == 1


def test_import_does_not_apply_snack_stock_when_sale_already_inserted() -> None:
    sales_store = InMemoryMachineSalesStore()
    stock_store = InMemorySnackMachineStockStore()
    map_store = InMemoryKitMatrixDeployMapStore()
    map_store.upsert(
        kit_matrix_id=42,
        logical_matrix_name="SnackA",
        machine_code="514",
        vending_machine_id=7,
        kit_matrix_name="n",
    )
    stock = SnackMachineStock(machine_code="514")
    stock.apply_inventory(
        as_of=datetime(2026, 7, 1, tzinfo=UTC),
        quantities={("514", "SnackA", 1): Decimal("5")},
        product_by_key={("514", "SnackA", 1): "SKU1"},
        inventory_id="i",
    )
    stock_store.save(stock)
    assert sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-snack-1",
            machine_id=MachineId("m-514"),
            product_code="SKU1",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
            sale_kind="snack",
            kit_matrix_id=42,
            kit_vending_machine_id=7,
            kit_line_number=1,
            machine_code="514",
        ),
    )

    service = ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=StubKitVendingClient(
            rows=[
                {
                    "source_id": "kv-snack-1",
                    "vending_machine_code": "514",
                    "product_code": "SKU1",
                    "quantity": "1",
                    "occurred_at": "2026-07-02T12:00:00Z",
                    "sale_kind": "snack",
                    "kit_matrix_id": "42",
                    "kit_vending_machine_id": "7",
                    "kit_line_number": "1",
                },
            ],
        ),
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=ApplySnackSaleToStock(
            stock_store=stock_store,
            deploy_map=map_store,
            snapshot_product_lookup=lambda **_: "SKU1",
        ),
    )

    result = service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    assert result.inserted == 0
    loaded = stock_store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "SnackA", 1) == Decimal("5")


def test_import_persists_resolve_status_after_apply() -> None:
    sales_store = InMemoryMachineSalesStore()
    service = ImportKitVendingSales(
        sales_store=sales_store,
        kitvending_client=StubKitVendingClient(
            rows=[
                {
                    "source_id": "kv-unresolved-1",
                    "vending_machine_code": "514",
                    "product_code": "SKU1",
                    "quantity": "1",
                    "occurred_at": "2026-07-02T12:00:00Z",
                    "sale_kind": "snack",
                    "kit_matrix_id": "99",
                    "kit_vending_machine_id": "7",
                    "kit_line_number": "1",
                },
            ],
        ),
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=ApplySnackSaleToStock(
            stock_store=InMemorySnackMachineStockStore(),
            deploy_map=InMemoryKitMatrixDeployMapStore(),
            snapshot_product_lookup=lambda **_: None,
        ),
    )

    service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    sales = sales_store.find_in_window(
        MachineId("m-514"),
        opened_at=datetime(2026, 7, 1, tzinfo=UTC),
        closed_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert len(sales) == 1
    assert sales[0].resolve_status == "unresolved_matrix"


def test_unresolved_alert_fires_at_threshold() -> None:
    notifier = _RecordingUnresolvedAlertNotifier()
    apply = ApplySnackSaleToStock(
        stock_store=InMemorySnackMachineStockStore(),
        deploy_map=InMemoryKitMatrixDeployMapStore(),
        snapshot_product_lookup=lambda **_: None,
    )
    service = ImportKitVendingSales(
        sales_store=InMemoryMachineSalesStore(),
        kitvending_client=StubKitVendingClient(rows=_unresolved_snack_rows(10)),
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=apply,
        unresolved_alert_min=10,
        unresolved_alert_notifier=notifier,
    )

    service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    assert notifier.alerts == [10]


def test_unresolved_alert_not_fired_below_threshold() -> None:
    notifier = _RecordingUnresolvedAlertNotifier()
    apply = ApplySnackSaleToStock(
        stock_store=InMemorySnackMachineStockStore(),
        deploy_map=InMemoryKitMatrixDeployMapStore(),
        snapshot_product_lookup=lambda **_: None,
    )
    service = ImportKitVendingSales(
        sales_store=InMemoryMachineSalesStore(),
        kitvending_client=StubKitVendingClient(rows=_unresolved_snack_rows(9)),
        code_resolver=MappingVendingMachineCodeResolver({"514": MachineId("m-514")}),
        apply_snack_sale=apply,
        unresolved_alert_min=10,
        unresolved_alert_notifier=notifier,
    )

    service.execute(since=datetime(2026, 7, 1, tzinfo=UTC))

    assert notifier.alerts == []
