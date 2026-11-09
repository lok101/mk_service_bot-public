from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.layout_parse import layouts_to_parse_state
from src.application.matrix_automation.models import (
    PriceSnapshotDocument,
    SnapshotLineRecord,
)
from src.application.matrix_automation.run_matrix_deploy_build import (
    PurchaseFetchGlobalAbort,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)

from .fakes import (
    _FailingIfCalledStockProvider,
    _FailOnReadSnapshotStore,
    _FixedStockProvider,
    _KeyedSnapshotStore,
    _multi_machine_store,
    _RecordingPurchaseReader,
    _runner,
    _single_cell_state,
    _store_with_current,
    _two_machine_state,
)


def test_guard_enabled_adds_snapshot_current_to_purchase_batch() -> None:
    reader = _RecordingPurchaseReader(prices={"NEW": ("20", 10), "OLD": ("10", 12)})
    runner = _runner(
        reader=reader,
        snapshot_store=_store_with_current("OLD"),
        guard_enabled=True,
        stock_provider=_FixedStockProvider(0),
    )
    runner(_single_cell_state(desired="NEW"))
    assert reader.calls == [frozenset({"NEW", "OLD"})]


def test_guard_disabled_fetches_only_catalog_and_does_not_prescan_snapshot() -> None:
    reader = _RecordingPurchaseReader(prices={"NEW": ("20", 10)})
    store = _FailOnReadSnapshotStore(reader=reader)
    runner = _runner(reader=reader, snapshot_store=store, guard_enabled=False)
    runner(_single_cell_state(desired="NEW"))
    assert reader.calls == [frozenset({"NEW"})]


def test_guard_union_is_fetched_once_for_all_units() -> None:
    reader = _RecordingPurchaseReader(
        prices={
            "NEW-1": ("20", 10),
            "NEW-2": ("30", 11),
            "OLD": ("10", 12),
        }
    )
    store = _multi_machine_store(
        {"512": "OLD", "513": "OLD"},
        purchase_reader=reader,
    )
    runner = _runner(
        reader=reader,
        snapshot_store=store,
        guard_enabled=True,
        stock_provider=_FixedStockProvider(0),
    )
    runner(_two_machine_state(desired_codes=("NEW-1", "NEW-2")))
    assert reader.calls == [frozenset({"NEW-1", "NEW-2", "OLD"})]
    machines_scanned = {key[0] for key in store.prescan_lookups}
    assert machines_scanned == {"512", "513"}


def test_guard_disabled_product_change_uses_catalog_only_batch_and_applies_desired() -> None:
    reader = _RecordingPurchaseReader(prices={"NEW": ("10", 10)})
    provider = _FailingIfCalledStockProvider()
    result = _runner(
        reader=reader,
        snapshot_store=_store_with_current("OLD"),
        guard_enabled=False,
        stock_provider=provider,
    )(_single_cell_state(desired="NEW"))
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert reader.calls == [frozenset({"NEW"})]
    assert result.payloads[0].lines[0].product_code == "NEW"
    assert result.payloads[0].lines[0].outcome == "applied"


def test_missing_guard_current_ms_attributes_keeps_atomic_snapshot_and_unit_deployable() -> None:
    reader = _RecordingPurchaseReader(prices={"NEW": ("10", 10)})
    store = _KeyedSnapshotStore(
        {
            ("512", "Snacks", 1): PriceSnapshotDocument(
                job_id="job-1",
                machine_code="512",
                logical_matrix_name="Snacks",
                recorded_at="2026-07-08T10:00:00Z",
                lines=(
                    SnapshotLineRecord(
                        line_number=1,
                        product_code="OLD",
                        product_name="Prev",
                        capacity=12,
                        purchase_price="10.00",
                        calculated_price="60.00",
                        deploy_price="60.00",
                        outcome="applied",
                        reason=None,
                        strong_price_increase=False,
                    ),
                ),
            ),
        }
    )
    result = _runner(
        reader=reader,
        snapshot_store=store,
        guard_enabled=True,
        stock_provider=_FixedStockProvider(2),
    )(_single_cell_state(desired="NEW"))
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert result.skipped_units == ()
    line = result.payloads[0].lines[0]
    assert (line.product_code, line.outcome) == ("OLD", "product_swap_blocked")
    assert (line.deploy_price, line.capacity) == (Decimal("60"), 12)


def test_build_keeps_effective_when_substitution_blocks_desired() -> None:
    layouts = InMemorySnackMachineLayoutStore()
    layouts.upsert(
        SnackMachineLayout(
            machine_code="512",
            logical_matrix_name="Snacks",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "NEW"),),
        )
    )
    state = layouts_to_parse_state(layouts.list_all())
    reader = _RecordingPurchaseReader(prices={"NEW": ("10", 10)})
    store = _KeyedSnapshotStore(
        {
            ("512", "Snacks", 1): PriceSnapshotDocument(
                job_id="job-1",
                machine_code="512",
                logical_matrix_name="Snacks",
                recorded_at="2026-07-08T10:00:00Z",
                lines=(
                    SnapshotLineRecord(
                        line_number=1,
                        product_code="OLD",
                        product_name="Prev",
                        capacity=12,
                        purchase_price="10.00",
                        calculated_price="60.00",
                        deploy_price="60.00",
                        outcome="applied",
                        reason=None,
                        strong_price_increase=False,
                    ),
                ),
            ),
        }
    )
    result = _runner(
        reader=reader,
        snapshot_store=store,
        guard_enabled=True,
        stock_provider=_FixedStockProvider(2),
    )(state)
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    line = result.payloads[0].lines[0]
    assert line.outcome == "product_swap_blocked"
    assert line.product_code == "OLD"
