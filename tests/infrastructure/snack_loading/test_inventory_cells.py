from __future__ import annotations

from collections.abc import Sequence

from src.application.matrix_automation.models import (
    PriceSnapshotDocument,
    SkuPriceOutcome,
    SnapshotLineRecord,
)
from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.application.snack_loading.ports import InventoryFormCell
from src.infrastructure.snack_loading.inventory_cells import (
    SnapshotSnackInventoryCellsSource,
)


class _FakeSnapshotStore:
    """Minimal MatrixPriceSnapshotStore for list_cells (structural Protocol)."""

    def __init__(self, documents: tuple[PriceSnapshotDocument, ...]) -> None:
        self._documents = documents

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        del machine_code, logical_matrix_name
        return bool(self._documents)

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        del machine_code, logical_matrix_name, line_number
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> Sequence[PriceSnapshotDocument]:
        assert machine_code == "512"
        return self._documents

    def save(self, document: PriceSnapshotDocument) -> None:
        del document


def _line(
    *,
    line_number: int,
    product_code: str | None,
    outcome: SkuPriceOutcome,
    product_name: str = "Snack",
) -> SnapshotLineRecord:
    return SnapshotLineRecord(
        line_number=line_number,
        product_code=product_code,
        product_name=product_name,
        capacity=10,
        purchase_price="1.00",
        calculated_price="2.00",
        deploy_price="2.00",
        outcome=outcome,
        reason=None,
        strong_price_increase=False,
    )


def test_snapshot_snack_inventory_cells_lists_sorted_product_cells() -> None:
    """happy: applied lines with product_code → sorted cells with snapshot names."""
    docs = (
        PriceSnapshotDocument(
            job_id="job-b",
            machine_code="512",
            logical_matrix_name="B-Matrix",
            recorded_at="2026-08-06T10:00:00Z",
            lines=(
                _line(
                    line_number=2,
                    product_code="sku-2",
                    outcome="applied",
                    product_name="B Name",
                ),
            ),
        ),
        PriceSnapshotDocument(
            job_id="job-a",
            machine_code="512",
            logical_matrix_name="A-Matrix",
            recorded_at="2026-08-06T10:00:00Z",
            lines=(
                _line(
                    line_number=5,
                    product_code="sku-5",
                    outcome="applied",
                    product_name="A5",
                ),
                _line(
                    line_number=1,
                    product_code="sku-1",
                    outcome="applied",
                    product_name="A1",
                ),
            ),
        ),
    )
    store: MatrixPriceSnapshotStore = _FakeSnapshotStore(docs)
    source = SnapshotSnackInventoryCellsSource(snapshot_store=store)
    assert source.list_cells("512") == (
        InventoryFormCell("A-Matrix", 1, "sku-1", "A1"),
        InventoryFormCell("A-Matrix", 5, "sku-5", "A5"),
        InventoryFormCell("B-Matrix", 2, "sku-2", "B Name"),
    )


def test_snapshot_snack_inventory_cells_skips_blocked_empty_and_blank_product() -> None:
    """edge: blocked_empty и пустой product_code не попадают в cells."""
    docs = (
        PriceSnapshotDocument(
            job_id="job-1",
            machine_code="512",
            logical_matrix_name="Snacks",
            recorded_at="2026-08-06T10:00:00Z",
            lines=(
                _line(line_number=1, product_code="keep", outcome="applied"),
                _line(line_number=2, product_code=None, outcome="blocked_empty"),
                _line(line_number=3, product_code="", outcome="applied"),
                _line(line_number=4, product_code=None, outcome="applied"),
            ),
        ),
    )
    store: MatrixPriceSnapshotStore = _FakeSnapshotStore(docs)
    source = SnapshotSnackInventoryCellsSource(snapshot_store=store)
    assert source.list_cells("512") == (InventoryFormCell("Snacks", 1, "keep", "Snack"),)
