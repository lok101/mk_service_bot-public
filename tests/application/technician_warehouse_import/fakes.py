from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
)
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ExternalWarehouseMoveLine,
    ReadMovesResult,
    TechnicianWarehouseTransferReader,
)
from src.domain.ids import EventId, TechnicianId
from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
from src.domain.technician_warehouse.events import TechnicianWarehouseTransferObserved
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
)
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_PREVIOUS = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_ANCHOR = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)


def _coffee_spec() -> ProductSpec:
    unit = ProductUnit.PIECE
    return ProductSpec(
        product_code="coffee",
        name="Coffee",
        unit=unit,
        pack_size=Decimal("1"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


_PRODUCT_RESOLVER = MappingProductSpecByCodeResolver(
    {
        "coffee-rich": _coffee_spec(),
        "coffee-id": _coffee_spec(),
        "coffee-rich-alias": _coffee_spec(),
    },
)


_CATALOG_RESOLVER = MoySkladCatalogBaseQuantityResolver(product_resolver=_PRODUCT_RESOLVER)


@dataclass(slots=True)
class FakeTransferReader(TechnicianWarehouseTransferReader):
    moves: tuple[ExternalWarehouseMove, ...] = ()
    skipped_unresolved: int = 0
    calls: list[tuple[datetime, datetime]] = field(default_factory=list)
    ensure_calls: list[tuple[str, ...]] = field(default_factory=list)
    ensure_error: Exception | None = None
    read_error: Exception | None = None

    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None:
        self.ensure_calls.append(codes)
        if self.ensure_error is not None:
            raise self.ensure_error

    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult:
        _ = technician_store_code
        self.calls.append((moment_from, moment_to))
        if self.read_error is not None:
            raise self.read_error
        return ReadMovesResult(
            moves=self.moves,
            skipped_unresolved=self.skipped_unresolved,
        )


def _supply_in(
    doc_id: str,
    *,
    product_code: str = "coffee-rich",
    quantity: str = "10",
    updated_at: datetime | None = None,
    source_store_code: str = "main",
    target_store_code: str = "tech-1",
) -> ExternalWarehouseMove:
    moment = updated_at or _T1
    resolved_updated_at = updated_at or moment
    return ExternalWarehouseMove(
        document_id=doc_id,
        source_store_code=source_store_code,
        target_store_code=target_store_code,
        moment=moment,
        updated_at=resolved_updated_at,
        lines=(
            ExternalWarehouseMoveLine(
                product_code=product_code,
                product_name=product_code,
                quantity=Decimal(quantity),
            ),
        ),
    )


def _supply_in_with_lines(
    doc_id: str,
    *line_specs: tuple[str, str],
) -> ExternalWarehouseMove:
    """line_specs: (product_code, quantity_str)."""
    moment = _T1
    return ExternalWarehouseMove(
        document_id=doc_id,
        source_store_code="main",
        target_store_code="tech-1",
        moment=moment,
        updated_at=moment,
        lines=tuple(
            ExternalWarehouseMoveLine(
                product_code=code,
                product_name=code,
                quantity=Decimal(qty),
            )
            for code, qty in line_specs
        ),
    )


def _supply_return(doc_id: str, *, quantity: str = "3") -> ExternalWarehouseMove:
    return _supply_in(
        doc_id,
        quantity=quantity,
        source_store_code="tech-1",
        target_store_code="main",
    )


def _technician_to_machine(doc_id: str) -> ExternalWarehouseMove:
    return _supply_in(
        doc_id,
        source_store_code="tech-1",
        target_store_code="vm-01",
    )


def _repository(
    *,
    previous_inventory_at: datetime | None = None,
) -> InMemoryTechnicianWarehouseRepository:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    if previous_inventory_at is not None:
        warehouse = repository.get(_TECHNICIAN_ID)
        warehouse.count_inventory(
            inventory_id="inv-previous",
            form_token="token-previous",
            counted_at=previous_inventory_at,
            actual_by_sku={"coffee": Decimal("10")},
            baseline=False,
        )
        repository.save(warehouse, expected_version=0)
    return repository


def _importer(
    *,
    previous_inventory_at: datetime | None = None,
    lookback_days: int = 60,
    supply_store_codes: tuple[str, ...] = ("main",),
    reader: FakeTransferReader | None = None,
    repository: InMemoryTechnicianWarehouseRepository | None = None,
) -> tuple[ImportTechnicianWarehouseTransfers, FakeTransferReader]:
    resolved_reader = reader or FakeTransferReader()
    resolved_repository = repository or _repository(previous_inventory_at=previous_inventory_at)
    importer = ImportTechnicianWarehouseTransfers(
        reader=resolved_reader,
        catalog_base_quantity_resolver=_CATALOG_RESOLVER,
        executor=TechnicianWarehouseExecutor(repository=resolved_repository),
        supply_store_codes=supply_store_codes,
        lookback_days=lookback_days,
    )
    return importer, resolved_reader


def _run_import(
    *moves: ExternalWarehouseMove,
) -> tuple[object, object]:
    reader = FakeTransferReader(moves=moves)
    importer, _ = _importer(reader=reader)
    result = asyncio.run(importer.execute(_TECHNICIAN_ID, anchor_at=_ANCHOR))
    warehouse = importer.executor.repository.get(_TECHNICIAN_ID)
    return result, warehouse


def _repeatable_import_case() -> tuple[
    ImportTechnicianWarehouseTransfers,
    InMemoryTechnicianWarehouseRepository,
]:
    reader = FakeTransferReader(moves=(_supply_in("move-1"),))
    repository = _repository()
    importer, _ = _importer(reader=reader, repository=repository)
    return importer, repository


def _importer_with_finalized_move(doc_id: str) -> ImportTechnicianWarehouseTransfers:
    repository = _repository()
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.observe_transfer(
        TechnicianWarehouseTransferObserved(
            event_id=EventId("evt-finalized"),
            technician_id=_TECHNICIAN_ID,
            occurred_at=_T1,
            external_document_id=doc_id,
            moment=_T1,
            updated_at=_T1,
            observed_at=_T1,
            content_hash="hash-v1",
            direction=TransferDirection.SUPPLY_IN,
            lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("10")),),
        ),
    )
    warehouse.finalize_transfers(
        session_id="session-1",
        external_document_ids=(doc_id,),
        finalized_at=_T2,
    )
    repository.save(warehouse, expected_version=0)
    reader = FakeTransferReader(moves=(_supply_in(doc_id),))
    importer, _ = _importer(reader=reader, repository=repository)
    return importer


@dataclass(slots=True)
class ErrorTransferReader(TechnicianWarehouseTransferReader):
    error: Exception

    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None:
        _ = codes

    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult:
        _ = technician_store_code, moment_from, moment_to
        raise self.error
