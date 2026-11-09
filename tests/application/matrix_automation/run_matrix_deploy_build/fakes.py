from __future__ import annotations

from decimal import Decimal

from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
    SnapshotLineRecord,
)
from src.application.matrix_automation.ports import (
    MatrixPriceSnapshotStore,
    MatrixStockProvider,
)
from src.application.matrix_automation.run_matrix_deploy_build import (
    RunMatrixDeployBuild,
)
from src.domain.matrix_pricing.formula import BaseMarginParams


class _CountingPurchaseReader:
    def __init__(
        self,
        *,
        prices: dict[str, tuple[str, int]],
        cards_found: int | None = None,
    ) -> None:
        self._prices = prices
        self._cards_found = cards_found
        self.fetch_count = 0

    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        self.fetch_count += 1
        attributes = {code: self._prices[code] for code in product_codes if code in self._prices}
        found = self._cards_found if self._cards_found is not None else len(attributes)
        return PurchaseAttributesFetchResult(attributes=attributes, cards_found=found)


class _RecordingPurchaseReader:
    def __init__(self, *, prices: dict[str, tuple[str, int]]) -> None:
        self._prices = prices
        self.calls: list[frozenset[str]] = []

    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        self.calls.append(product_codes)
        attributes = {code: self._prices[code] for code in product_codes if code in self._prices}
        return PurchaseAttributesFetchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


class _SnapshotStore:
    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return False

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: object) -> None:
        return None


class _SnapshotStoreWithUnits:
    def __init__(self, *, has_snapshot_for: set[tuple[str, str]]) -> None:
        self._has_snapshot_for = has_snapshot_for

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return (logical_matrix_name, machine_code) in self._has_snapshot_for

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: object) -> None:
        return None


def _base_margin() -> BaseMarginParams:
    return curved_margin_params()


def _enabled_matrix(
    *,
    name: str,
    machines: tuple[str, ...],
    product: str,
) -> EnabledLogicalMatrix:
    return EnabledLogicalMatrix(
        logical_matrix_name=name,
        machine_codes=machines,
        matrix_multiplier=Decimal("1"),
        cells=(MatrixCatalogCell(1, "Product", product),),
    )


class _FailOnReadSnapshotStore:
    """Fails if snapshot is read before purchase fetch (guard pre-scan)."""

    def __init__(self, *, reader: _RecordingPurchaseReader) -> None:
        self._reader = reader

    def _assert_not_prescan(self) -> None:
        if not self._reader.calls:
            raise AssertionError("snapshot must not be read when guard is disabled")

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        self._assert_not_prescan()
        return False

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        self._assert_not_prescan()
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: object) -> None:
        return None


def _snapshot_document(
    *,
    machine_code: str,
    product_code: str,
    line_number: int = 1,
    logical_matrix_name: str = "Snacks",
) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id="job-1",
        machine_code=machine_code,
        logical_matrix_name=logical_matrix_name,
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=line_number,
                product_code=product_code,
                product_name="Prev",
                capacity=12,
                purchase_price="10.00",
                calculated_price="50.00",
                deploy_price="50.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


class _KeyedSnapshotStore:
    def __init__(
        self,
        mapping: dict[tuple[str, str, int], PriceSnapshotDocument],
        *,
        purchase_reader: _RecordingPurchaseReader | None = None,
    ) -> None:
        self._mapping = mapping
        self._purchase_reader = purchase_reader
        self.prescan_lookups: list[tuple[str, str, int]] = []

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        key = (machine_code, logical_matrix_name, line_number)
        if self._purchase_reader is not None and not self._purchase_reader.calls:
            self.prescan_lookups.append(key)
        return self._mapping.get(key)

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return any(
            key[0] == machine_code and key[1] == logical_matrix_name for key in self._mapping
        )

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: PriceSnapshotDocument) -> None:
        return None


def _store_with_current(product_code: str) -> _KeyedSnapshotStore:
    return _KeyedSnapshotStore(
        {
            ("512", "Snacks", 1): _snapshot_document(
                machine_code="512",
                product_code=product_code,
            ),
        }
    )


def _multi_machine_store(
    by_machine: dict[str, str],
    *,
    purchase_reader: _RecordingPurchaseReader | None = None,
) -> _KeyedSnapshotStore:
    return _KeyedSnapshotStore(
        {
            (machine_code, "Snacks", 1): _snapshot_document(
                machine_code=machine_code,
                product_code=product_code,
            )
            for machine_code, product_code in by_machine.items()
        },
        purchase_reader=purchase_reader,
    )


def _two_machine_state(*, desired_codes: tuple[str, str]) -> MatrixParseState:
    return _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512", "513"),
                matrix_multiplier=Decimal("1"),
                cells=(
                    MatrixCatalogCell(1, "New-1", desired_codes[0]),
                    MatrixCatalogCell(2, "New-2", desired_codes[1]),
                ),
            ),
        ),
    )


def _state(*, matrices: tuple[EnabledLogicalMatrix, ...]) -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=matrices,
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )


def _single_cell_state(*, desired: str) -> MatrixParseState:
    return _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "New", desired),),
            ),
        ),
    )


def _runner(
    *,
    reader: _CountingPurchaseReader | _RecordingPurchaseReader,
    snapshot_store: MatrixPriceSnapshotStore | None = None,
    guard_enabled: bool = False,
    product_multipliers: dict[str, Decimal] | None = None,
    stock_provider: MatrixStockProvider | None = None,
) -> RunMatrixDeployBuild:
    multipliers = product_multipliers or {
        "MS-1": Decimal("1"),
        "MS-2": Decimal("1"),
        "NEW": Decimal("1"),
        "OLD": Decimal("1"),
        "NEW-1": Decimal("1"),
        "NEW-2": Decimal("1"),
    }
    return RunMatrixDeployBuild(
        snapshot_store=snapshot_store or _SnapshotStore(),
        purchase_reader=reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers=multipliers,
        substitution_guard_enabled=guard_enabled,
        stock_provider=stock_provider,
    )


class _FixedStockProvider:
    def __init__(self, stock: int | None) -> None:
        self._stock = stock

    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        return self._stock


class _FailingIfCalledStockProvider:
    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        raise AssertionError("stock provider must not be called when guard is disabled")
