from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.matrix_automation import PriceSnapshotDocument, SnapshotLineRecord
from src.application.snack_loading.apply_sale import ApplySnackSaleToStock
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.domain.snack_loading import SnackMachineStock
from src.infrastructure.composition.factories.settlement import _product_from_matrix_snapshot
from src.infrastructure.matrix_automation.memory_snapshots import InMemoryMatrixPriceSnapshotStore
from src.infrastructure.testing.snack_loading_fakes import (
    InMemoryKitMatrixDeployMapStore,
    InMemorySnackMachineStockStore,
)


def _snapshot_doc(*, product_code: str) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id="job-1",
        machine_code="514",
        logical_matrix_name="SnackA",
        recorded_at="2026-07-01T00:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code=product_code,
                product_name="Snack",
                capacity=10,
                purchase_price="1.00",
                calculated_price="2.00",
                deploy_price="2.00",
                outcome="applied",  # type: ignore[arg-type]
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


def test_apply_uses_matrix_snapshot_product_for_mismatch() -> None:
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

    snapshot_store = InMemoryMatrixPriceSnapshotStore()
    snapshot_store.save(_snapshot_doc(product_code="OTHER"))

    apply = ApplySnackSaleToStock(
        stock_store=stock_store,
        deploy_map=map_store,
        snapshot_product_lookup=lambda **kwargs: _product_from_matrix_snapshot(
            snapshot_store,
            machine_code=str(kwargs["machine_code"]),
            logical_matrix_name=str(kwargs["logical_matrix_name"]),
            line_number=kwargs["line_number"],  # type: ignore[arg-type]
        ),
    )

    result = apply.execute(
        MachineSale(
            source_id="s1",
            machine_id=MachineId("m1"),
            product_code="SKU1",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
            ingested_at=datetime(2026, 7, 2, tzinfo=UTC),
            sale_kind="snack",
            kit_matrix_id=42,
            kit_vending_machine_id=7,
            kit_line_number=1,
            machine_code="514",
        ),
    )

    assert result.resolve_status == "product_mismatch"
    loaded = stock_store.load("514")
    assert loaded is not None
    assert loaded.qty("514", "SnackA", 1) == Decimal("5")
