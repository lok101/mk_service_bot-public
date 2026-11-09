from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from beartype import beartype

from src.application.matrix_automation.job_models import MatrixDeployJob
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.models import (
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployResult,
    MatrixParseState,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
)
from src.application.matrix_automation.snack_machine_layout import SnackMachineLayout
from src.domain.matrix_pricing.formula import BaseMarginParams

if TYPE_CHECKING:
    from src.application.matrix_automation.run_matrix_deploy_build import PurchaseFetchGlobalAbort


@runtime_checkable
class MatrixBaseMarginStore(Protocol):
    @beartype
    def get(self) -> BaseMarginParams | None: ...

    @beartype
    def save(self, params: BaseMarginParams) -> None: ...


@runtime_checkable
class SnackMachineLayoutStore(Protocol):
    @beartype
    def get(self, machine_code: str) -> SnackMachineLayout | None: ...

    @beartype
    def upsert(self, layout: SnackMachineLayout) -> None: ...

    @beartype
    def list_all(self) -> tuple[SnackMachineLayout, ...]: ...

    @beartype
    def count(self) -> int: ...


@runtime_checkable
class MatrixSkuCatalogStore(Protocol):
    @beartype
    def get(self, product_code: str) -> MatrixSkuCatalogEntry | None: ...

    @beartype
    def upsert(self, entry: MatrixSkuCatalogEntry) -> None: ...

    @beartype
    def list_all(self) -> tuple[MatrixSkuCatalogEntry, ...]: ...


@runtime_checkable
class MatrixPriceSnapshotStore(Protocol):
    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool: ...
    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None: ...

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> Sequence[PriceSnapshotDocument]: ...

    def save(self, document: PriceSnapshotDocument) -> None: ...


@runtime_checkable
class PurchaseAttributesReader(Protocol):
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult: ...


@runtime_checkable
class BuildMatrixDeployPayloadsPort(Protocol):
    def __call__(self, state: MatrixParseState) -> BuildMatrixDeployResult: ...


@runtime_checkable
class RunMatrixDeployBuildPort(Protocol):
    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult | PurchaseFetchGlobalAbort: ...


@runtime_checkable
class MatrixDeployer(Protocol):
    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]: ...


@runtime_checkable
class MatrixDeployJobRepository(Protocol):
    def insert(self, job: MatrixDeployJob) -> None: ...

    def finalize(self, job: MatrixDeployJob) -> None: ...


@runtime_checkable
class MatrixWorkerStatusRepository(Protocol):
    def record_heartbeat(self, *, at: str, enabled: bool) -> None: ...

    def record_terminal_job(self, job: MatrixDeployJob) -> None: ...


@runtime_checkable
class MatrixJobNotifier(Protocol):
    def notify(
        self,
        job: MatrixDeployJob,
        *,
        global_abort_reason: str | None = None,
    ) -> None: ...


@runtime_checkable
class MatrixStockProvider(Protocol):
    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None: ...


@runtime_checkable
class MatrixCellLoadingPolicy(Protocol):
    def is_loading_blocked(
        self,
        *,
        desired_product: str | None,
        snapshot_product: str | None,
    ) -> bool: ...
