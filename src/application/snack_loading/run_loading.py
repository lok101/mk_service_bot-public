from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from time import sleep as default_sleep
from typing import Literal

from beartype import beartype

from src.application.matrix_automation.ports import MatrixCellLoadingPolicy
from src.application.snack_loading.loading_plan import (
    LoadingStrategy,
    SnackLoadingPlan,
    compute_snack_loading_plan,
)
from src.application.snack_loading.ports import (
    MatrixCatalogSync,
    SnackLoadingCellSource,
    SnackLoadingFailAfterMoveNotifier,
    SnackLoadingRunRecord,
    SnackLoadingRunStore,
    SnackMachineStockStore,
    SnackMainStockReader,
    SnackMoveClient,
    SnackStoreResolveError,
)
from src.domain.snack_loading.events import CellKey

RunMode = Literal["plan_only", "execute"]
ApparatusStatus = Literal["ok", "failed", "skipped"]


@beartype
@dataclass(frozen=True, slots=True)
class LoadingBatchInput:
    apparatus_codes: tuple[str, ...]
    strategy: LoadingStrategy
    percent: int | None = None


@beartype
@dataclass(frozen=True, slots=True)
class ApparatusRunResult:
    machine_code: str
    status: ApparatusStatus
    reason: str | None = None
    plan: SnackLoadingPlan | None = None
    move_id: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingRunResult:
    run_id: str
    apparatus_results: tuple[ApparatusRunResult, ...]
    exit_code: int
    stopped_early: bool = False


@beartype
@dataclass(slots=True)
class RunSnackLoading:
    stock_store: SnackMachineStockStore
    catalog_sync: MatrixCatalogSync
    cell_source: SnackLoadingCellSource
    main_stock: SnackMainStockReader
    move_client: SnackMoveClient
    run_store: SnackLoadingRunStore
    alert_notifier: SnackLoadingFailAfterMoveNotifier
    loading_policy: MatrixCellLoadingPolicy
    min_move_fraction: float
    handle_food_products: bool = True
    machine_interval_seconds: float = 0.0
    batch_gap_seconds: float = 0.0
    sleeper: Callable[[float], None] = field(default=default_sleep)

    @beartype
    def execute(
        self,
        *,
        batches: Sequence[LoadingBatchInput],
        mode: RunMode,
        run_id: str,
        resume_run_id: str | None = None,
    ) -> SnackLoadingRunResult:
        if resume_run_id is not None:
            return self._resume(resume_run_id=resume_run_id)

        self.catalog_sync.sync()
        main_available = self.main_stock.available_by_product()
        results: list[ApparatusRunResult] = []
        stopped_early = False
        any_failed = False

        for batch_index, batch in enumerate(batches):
            if stopped_early:
                break
            if mode == "execute" and batch_index > 0 and self.batch_gap_seconds > 0:
                self.sleeper(self.batch_gap_seconds)
            for machine_index, machine_code in enumerate(batch.apparatus_codes):
                if stopped_early:
                    break
                if mode == "execute" and machine_index > 0 and self.machine_interval_seconds > 0:
                    self.sleeper(self.machine_interval_seconds)
                apparatus_result = self._process_apparatus(
                    machine_code=machine_code,
                    batch=batch,
                    mode=mode,
                    run_id=run_id,
                    main_available=main_available,
                    refresh_main=(mode == "execute"),
                )
                results.append(apparatus_result)
                if apparatus_result.status == "failed":
                    any_failed = True
                    if apparatus_result.reason == "fail_after_move":
                        stopped_early = True

        exit_code = 1 if any_failed or stopped_early else 0
        return SnackLoadingRunResult(
            run_id=run_id,
            apparatus_results=tuple(results),
            exit_code=exit_code,
            stopped_early=stopped_early,
        )

    @beartype
    def _resume(self, *, resume_run_id: str) -> SnackLoadingRunResult:
        record = self.run_store.get(resume_run_id)
        if record is None:
            return SnackLoadingRunResult(
                run_id=resume_run_id,
                apparatus_results=(
                    ApparatusRunResult(
                        machine_code="",
                        status="failed",
                        reason="unknown_run",
                    ),
                ),
                exit_code=1,
            )
        if record.domain_applied:
            return SnackLoadingRunResult(
                run_id=resume_run_id,
                apparatus_results=(
                    ApparatusRunResult(
                        machine_code=record.machine_code,
                        status="ok",
                        reason="already_applied",
                        move_id=record.move_id,
                    ),
                ),
                exit_code=0,
            )
        self._apply_domain(
            machine_code=record.machine_code,
            run_id=record.run_id,
            move_id=record.move_id,
            increments={key: qty for key, qty in record.increments},
        )
        updated = SnackLoadingRunRecord(
            run_id=record.run_id,
            machine_code=record.machine_code,
            move_id=record.move_id,
            increments=record.increments,
            domain_applied=True,
        )
        self.run_store.save(updated)
        return SnackLoadingRunResult(
            run_id=resume_run_id,
            apparatus_results=(
                ApparatusRunResult(
                    machine_code=record.machine_code,
                    status="ok",
                    move_id=record.move_id,
                ),
            ),
            exit_code=0,
        )

    @beartype
    def _process_apparatus(
        self,
        *,
        machine_code: str,
        batch: LoadingBatchInput,
        mode: RunMode,
        run_id: str,
        main_available: dict[str, Decimal],
        refresh_main: bool,
    ) -> ApparatusRunResult:
        stock = self.stock_store.load(machine_code)
        if stock is None or not stock.has_completed_inventory:
            return ApparatusRunResult(
                machine_code=machine_code,
                status="failed",
                reason="no_inventory",
            )

        if refresh_main:
            main_available.clear()
            main_available.update(self.main_stock.available_by_product())

        cells = tuple(self.cell_source.list_plan_cells(machine_code))
        if not cells:
            return ApparatusRunResult(
                machine_code=machine_code,
                status="failed",
                reason="no_snapshot",
            )

        plan = compute_snack_loading_plan(
            machine_code=machine_code,
            strategy=batch.strategy,
            percent=batch.percent,
            cells=cells,
            main_available=main_available,
            min_move_fraction=self.min_move_fraction,
            loading_policy=self.loading_policy,
            handle_food_products=self.handle_food_products,
        )

        if mode == "plan_only":
            return ApparatusRunResult(
                machine_code=machine_code,
                status="ok",
                plan=plan,
            )

        if not plan.positions:
            return ApparatusRunResult(
                machine_code=machine_code,
                status="skipped",
                reason="empty_plan",
                plan=plan,
            )

        positions = tuple((p.product_code, p.quantity) for p in plan.positions)
        try:
            move_id = self.move_client.create_move(
                machine_code=machine_code,
                positions=positions,
            )
        except SnackStoreResolveError:
            return ApparatusRunResult(
                machine_code=machine_code,
                status="failed",
                reason="no_store",
                plan=plan,
            )
        except Exception:  # noqa: BLE001 — MS fail: continue batch
            return ApparatusRunResult(
                machine_code=machine_code,
                status="failed",
                reason="ms_create_move_failed",
                plan=plan,
            )

        increments: dict[CellKey, Decimal] = {
            line.cell_key: line.final_shipped for line in plan.lines if line.final_shipped > 0
        }
        record = SnackLoadingRunRecord(
            run_id=run_id,
            machine_code=machine_code,
            move_id=move_id,
            increments=tuple(sorted(increments.items())),
            domain_applied=False,
        )
        self.run_store.save(record)

        try:
            self._apply_domain(
                machine_code=machine_code,
                run_id=run_id,
                move_id=move_id,
                increments=increments,
            )
        except Exception:  # noqa: BLE001 — fail-after-move
            self.alert_notifier.notify_fail_after_move(
                machine_code=machine_code,
                move_id=move_id,
                run_id=run_id,
            )
            return ApparatusRunResult(
                machine_code=machine_code,
                status="failed",
                reason="fail_after_move",
                plan=plan,
                move_id=move_id,
            )

        self.run_store.save(
            SnackLoadingRunRecord(
                run_id=run_id,
                machine_code=machine_code,
                move_id=move_id,
                increments=record.increments,
                domain_applied=True,
            )
        )
        return ApparatusRunResult(
            machine_code=machine_code,
            status="ok",
            plan=plan,
            move_id=move_id,
        )

    @beartype
    def _apply_domain(
        self,
        *,
        machine_code: str,
        run_id: str,
        move_id: str,
        increments: dict[CellKey, Decimal],
    ) -> None:
        stock = self.stock_store.load(machine_code)
        if stock is None:
            msg = f"stock missing for {machine_code}"
            raise RuntimeError(msg)
        stock.apply_loading(
            run_id=run_id,
            move_id=move_id,
            increments=increments,
            occurred_at=datetime.now(tz=UTC),
        )
        self.stock_store.save(stock)
