from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixDeployPayloadLine,
    MatrixParseState,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
    SnapshotLineRecord,
)


class _RecordingStockProvider:
    def __init__(self, stock: int | None = 0) -> None:
        self.stock = stock
        self.calls: list[tuple[str, str, int, str]] = []

    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        self.calls.append((machine_code, logical_matrix_name, line_number, product_code))
        return self.stock


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


class _PurchaseReader:
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        attributes = {code: ("10.00", 12) for code in product_codes}
        return PurchaseAttributesFetchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


def _snapshot(
    *,
    product_code: str | None,
    product_name: str = "Старый",
    deploy_price: str = "60.00",
    capacity: int = 12,
    outcome: str = "applied",
    line_number: int = 1,
) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=line_number,
                product_code=product_code,
                product_name=product_name,
                capacity=capacity,
                purchase_price="10.00" if product_code is not None else None,
                calculated_price="60.00" if product_code is not None else None,
                deploy_price=deploy_price,
                outcome=outcome,  # type: ignore[arg-type]
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


def _state(
    *,
    desired: str | None,
    desired_name: str,
    line_number: int = 1,
) -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(line_number, desired_name, desired),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )


_PROVIDER_UNSET: object = object()


def _build_one(
    *,
    desired: str | None,
    current: str | None = None,
    desired_name: str | None = None,
    current_name: str = "Старый",
    current_snapshot_price: str = "60.00",
    current_snapshot_capacity: int = 12,
    current_snapshot_outcome: str = "applied",
    stock: int | None = 0,
    guard_enabled: bool = False,
    provider: _RecordingStockProvider | None | object = _PROVIDER_UNSET,
    purchase_attributes: dict[str, tuple[str, int]] | None = None,
    job_id: str = "test",
) -> MatrixDeployPayloadLine:
    if desired_name is None:
        desired_name = "" if desired is None else f"Product {desired}"
    documents: list[PriceSnapshotDocument] = []
    if current is not None or current_snapshot_outcome == "blocked_empty":
        documents.append(
            _snapshot(
                product_code=current,
                product_name=current_name,
                deploy_price=current_snapshot_price,
                capacity=current_snapshot_capacity,
                outcome=current_snapshot_outcome,
            ),
        )
    attrs = purchase_attributes
    if attrs is None:
        attrs = {}
        if desired is not None:
            attrs[desired] = ("10.00", 12)
        if current is not None:
            attrs[current] = ("10.00", 12)
    if provider is _PROVIDER_UNSET:
        stock_provider: _RecordingStockProvider | None = (
            _RecordingStockProvider(stock=stock) if guard_enabled else None
        )
    else:
        stock_provider = provider  # type: ignore[assignment]
    multipliers = {code: Decimal("1") for code in attrs}
    result = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore(documents),
        purchase_reader=_PurchaseReader(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers=multipliers,
        purchase_attributes=attrs,
        substitution_guard_enabled=guard_enabled,
        stock_provider=stock_provider,
        job_id=job_id,
    )(_state(desired=desired, desired_name=desired_name))
    assert len(result.payloads) == 1
    assert len(result.payloads[0].lines) == 1
    return result.payloads[0].lines[0]


class _PerCellStockProvider:
    def __init__(self, by_line: dict[int, int | None | BaseException]) -> None:
        self._by_line = by_line

    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        value = self._by_line[line_number]
        if isinstance(value, BaseException):
            raise value
        return value


def _build_two_cells(
    *,
    provider: _PerCellStockProvider,
    job_id: str = "test",
):
    from src.application.matrix_automation.models import BuildMatrixDeployResult

    document = PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="OLD-1",
                product_name="Old-1",
                capacity=12,
                purchase_price="10.00",
                calculated_price="60.00",
                deploy_price="60.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
            SnapshotLineRecord(
                line_number=2,
                product_code="OLD-2",
                product_name="Old-2",
                capacity=12,
                purchase_price="10.00",
                calculated_price="60.00",
                deploy_price="60.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    attrs = {
        "OLD-1": ("10.00", 12),
        "NEW-1": ("10.00", 12),
        "OLD-2": ("10.00", 12),
        "NEW-2": ("10.00", 12),
    }
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(
                    MatrixCatalogCell(1, "New-1", "NEW-1"),
                    MatrixCatalogCell(2, "New-2", "NEW-2"),
                ),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore([document]),
        purchase_reader=_PurchaseReader(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={code: Decimal("1") for code in attrs},
        purchase_attributes=attrs,
        substitution_guard_enabled=True,
        stock_provider=provider,
        job_id=job_id,
    )(state)
    assert isinstance(result, BuildMatrixDeployResult)
    return result


def _record(caplog: pytest.LogCaptureFixture, message: str) -> object:
    matching = [record for record in caplog.records if record.getMessage() == message]
    assert len(matching) == 1
    return matching[0]


def _extra(record: object) -> dict[str, object]:
    keys = (
        "job_id",
        "machine_code",
        "logical_matrix_name",
        "line_number",
        "product_code",
        "error",
    )
    return {key: getattr(record, key) for key in keys}
