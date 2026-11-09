from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
)
from src.domain.matrix_pricing.formula import BaseMarginParams


class _PurchaseReader:
    def __init__(
        self,
        *,
        prices: dict[str, tuple[str, int]] | None = None,
    ) -> None:
        self._prices = prices

    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        if self._prices is None:
            attributes = {code: ("10.00", 12) for code in product_codes}
        else:
            attributes = {
                code: self._prices[code] for code in product_codes if code in self._prices
            }
        return PurchaseAttributesFetchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


class _SnapshotStore:
    def __init__(self, documents: list[PriceSnapshotDocument] | None = None) -> None:
        self._documents = documents or []

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        matching = [
            doc
            for doc in self._documents
            if doc.machine_code == machine_code and doc.logical_matrix_name == logical_matrix_name
        ]
        if not matching:
            return None
        for doc in sorted(matching, key=lambda item: item.recorded_at, reverse=True):
            if any(line.line_number == line_number for line in doc.lines):
                return doc
        return None

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return any(
            doc.machine_code == machine_code and doc.logical_matrix_name == logical_matrix_name
            for doc in self._documents
        )

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: PriceSnapshotDocument) -> None:
        self._documents.append(document)


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
    ) -> PriceSnapshotDocument | None:
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: PriceSnapshotDocument) -> None:
        return None


class _UnusedPurchaseReader:
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        raise AssertionError("must not be called from builder")


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


def _builder(
    *,
    store: _SnapshotStore | None = None,
    prices: dict[str, tuple[str, int]] | None = None,
    sku_catalog_by_code: Mapping[str, MatrixSkuCatalogEntry] | None = None,
) -> BuildMatrixDeployPayloads:
    purchase_attributes = (
        {code: value for code, value in (prices or {}).items()}
        if prices is not None
        else {"MS-1": ("10.00", 12)}
    )
    return BuildMatrixDeployPayloads(
        snapshot_store=store or _SnapshotStore(),
        purchase_reader=_PurchaseReader(prices=prices),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={"MS-1": Decimal("1")},
        purchase_attributes=purchase_attributes,
        sku_catalog_by_code=sku_catalog_by_code,
    )
