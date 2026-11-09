from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_warehouse.delta import TechnicianWarehouseDeltaService
from src.application.technician_warehouse.errors import MoySkladUnavailable
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.import_ms_transfers import (
    ImportTechnicianWarehouseTransfers,
    TechnicianWarehouseImportResult,
)
from src.application.technician_warehouse.ports import (
    ExternalWarehouseMove,
    ExternalWarehouseMoveLine,
    ReadMovesResult,
    TechnicianWarehouseTransferReader,
)
from src.domain.ids import TechnicianId
from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
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


def _catalog_resolver(
    specs: dict[str, ProductSpec] | None = None,
) -> MoySkladCatalogBaseQuantityResolver:
    mapping = specs if specs is not None else {"coffee-rich": _coffee_spec()}
    return MoySkladCatalogBaseQuantityResolver(
        product_resolver=MappingProductSpecByCodeResolver(mapping),
    )


@dataclass(slots=True)
class RecordingImporter(ImportTechnicianWarehouseTransfers):
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult:
        self.calls.append((technician_id, anchor_at))
        return await super().execute(technician_id, anchor_at=anchor_at)


@dataclass(slots=True)
class FakeTransferReader(TechnicianWarehouseTransferReader):
    moves: tuple[ExternalWarehouseMove, ...] = ()

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
        return ReadMovesResult(moves=self.moves, skipped_unresolved=0)


def _supply_in(doc_id: str, *, quantity: str = "10") -> ExternalWarehouseMove:
    return ExternalWarehouseMove(
        document_id=doc_id,
        source_store_code="main",
        target_store_code="tech-1",
        moment=_T2,
        updated_at=_T2,
        lines=(
            ExternalWarehouseMoveLine(
                product_code="coffee-rich",
                product_name="Coffee",
                quantity=Decimal(quantity),
            ),
        ),
    )


def _supply_return(doc_id: str, *, quantity: str = "2") -> ExternalWarehouseMove:
    return ExternalWarehouseMove(
        document_id=doc_id,
        source_store_code="tech-1",
        target_store_code="main",
        moment=_T2,
        updated_at=_T2,
        lines=(
            ExternalWarehouseMoveLine(
                product_code="coffee-rich",
                product_name="Coffee",
                quantity=Decimal(quantity),
            ),
        ),
    )


def _repository_with_two_inventories() -> InMemoryTechnicianWarehouseRepository:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-baseline",
        form_token="baseline-token",
        counted_at=_PREVIOUS,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=False,
    )
    warehouse.observe_transfer(
        _supply_event("in-1", "10"),
    )
    warehouse.observe_transfer(
        _supply_event("ret-1", "2", direction="supply_return"),
    )
    from src.domain.ids import EventId, MachineId
    from src.domain.technician_warehouse.events import TechnicianWarehouseLoadingObserved
    from src.domain.technician_warehouse.models import TechnicianWarehouseLine

    warehouse.observe_loading(
        TechnicianWarehouseLoadingObserved(
            event_id=EventId("evt-loading-1"),
            technician_id=_TECHNICIAN_ID,
            occurred_at=_T2,
            source_event_id="loading-1",
            machine_id=MachineId("vm-01"),
            submitted_at=_T2,
            lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("5")),),
        ),
    )
    warehouse.count_inventory(
        inventory_id="inv-current",
        form_token="current-token",
        counted_at=_ANCHOR,
        actual_by_sku={"coffee": Decimal("21")},
        baseline=False,
    )
    repository.save(warehouse, expected_version=0)
    return repository


def _supply_event(
    external_document_id: str,
    quantity: str,
    *,
    direction: str = "supply_in",
) -> object:
    from src.domain.ids import EventId
    from src.domain.technician_warehouse.events import TechnicianWarehouseTransferObserved
    from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection

    resolved_direction = (
        TransferDirection.SUPPLY_IN if direction == "supply_in" else TransferDirection.SUPPLY_RETURN
    )
    return TechnicianWarehouseTransferObserved(
        event_id=EventId(f"evt-{external_document_id}"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=_T2,
        external_document_id=external_document_id,
        moment=_T2,
        updated_at=_T2,
        observed_at=_T2,
        content_hash=f"{external_document_id}:{quantity}",
        direction=resolved_direction,
        lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal(quantity)),),
    )


def _delta_case_with_two_inventories() -> tuple[TechnicianWarehouseDeltaService, RecordingImporter]:
    repository = _repository_with_two_inventories()
    reader = FakeTransferReader(moves=(_supply_in("in-1"), _supply_return("ret-1")))
    importer = RecordingImporter(
        reader=reader,
        catalog_base_quantity_resolver=_catalog_resolver(),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    port = TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)
    return port, importer


def _delta_case_with_baseline_only() -> TechnicianWarehouseDeltaService:
    """Seed-only stream (`baseline=True`) — no eligible form inventory session."""
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="seed:tech-1:t",
        form_token="seed:tech-1:t",
        counted_at=_PREVIOUS,
        actual_by_sku={"coffee": Decimal("20")},
        baseline=True,
    )
    repository.save(warehouse, expected_version=0)
    importer = RecordingImporter(
        reader=FakeTransferReader(),
        catalog_base_quantity_resolver=_catalog_resolver(),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    return TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)


def _delta_case_with_single_form_inventory() -> TechnicianWarehouseDeltaService:
    repository = InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )
    warehouse = repository.get(_TECHNICIAN_ID)
    warehouse.observe_transfer(_supply_event("in-1", "10"))
    from src.domain.ids import EventId, MachineId
    from src.domain.technician_warehouse.events import TechnicianWarehouseLoadingObserved
    from src.domain.technician_warehouse.models import TechnicianWarehouseLine

    warehouse.observe_loading(
        TechnicianWarehouseLoadingObserved(
            event_id=EventId("evt-loading-form-1"),
            technician_id=_TECHNICIAN_ID,
            occurred_at=_T2,
            source_event_id="loading-form-1",
            machine_id=MachineId("vm-01"),
            submitted_at=_T2,
            lines=(TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal("3")),),
        ),
    )
    warehouse.count_inventory(
        inventory_id="inv-form-1",
        form_token="form-token-1",
        counted_at=_ANCHOR,
        actual_by_sku={"coffee": Decimal("0")},
        baseline=False,
    )
    repository.save(warehouse, expected_version=0)
    importer = RecordingImporter(
        reader=FakeTransferReader(moves=(_supply_in("in-1"),)),
        catalog_base_quantity_resolver=_catalog_resolver(),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    return TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)


def _delta_case_with_unmatched(product_code: str) -> TechnicianWarehouseDeltaService:
    repository = _repository_with_two_inventories()
    importer = RecordingImporter(
        reader=FakeTransferReader(
            moves=(
                ExternalWarehouseMove(
                    document_id="bad",
                    source_store_code="main",
                    target_store_code="tech-1",
                    moment=_T2,
                    updated_at=_T2,
                    lines=(
                        ExternalWarehouseMoveLine(
                            product_code=product_code,
                            product_name="Unknown",
                            quantity=Decimal("1"),
                        ),
                    ),
                ),
            ),
        ),
        catalog_base_quantity_resolver=_catalog_resolver({}),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    return TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)


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


def _delta_case_with_import_error(error: Exception) -> TechnicianWarehouseDeltaService:
    repository = _repository_with_two_inventories()
    importer = RecordingImporter(
        reader=ErrorTransferReader(error=error),
        catalog_base_quantity_resolver=_catalog_resolver(),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    return TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)


def test_delta_port_imports_then_returns_non_baseline_delta() -> None:
    port, importer = _delta_case_with_two_inventories()
    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR))
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]
    assert delta is not None
    assert delta.warehouse_delta_by_sku == {"coffee": Decimal("-2")}


def test_delta_port_populates_breakdown_from_domain_aggregate() -> None:
    port, _importer = _delta_case_with_two_inventories()
    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR))
    assert delta is not None
    assert delta.previous_actual_by_sku["coffee"] == Decimal("20")
    assert delta.supply_in_by_sku["coffee"] == Decimal("10")
    assert delta.returns_by_sku["coffee"] == Decimal("2")
    assert delta.loadings_by_sku["coffee"] == Decimal("5")


def test_delta_port_returns_none_when_only_seed_baseline_exists() -> None:
    """edge: seed-only (`baseline=True`) → no session delta."""
    port = _delta_case_with_baseline_only()
    assert asyncio.run(port.get_delta(_TECHNICIAN_ID, after=None, until=_ANCHOR)) is None


def test_delta_port_returns_delta_for_single_form_inventory() -> None:
    # happy: sole form inventory → delta vs synthetic previous (empty previous_actual)
    port = _delta_case_with_single_form_inventory()
    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=None, until=_ANCHOR))
    assert delta is not None
    assert delta.warehouse_inventory_id == "inv-form-1"
    assert delta.inventory_moment == _ANCHOR
    assert delta.previous_actual_by_sku == {}
    assert delta.loadings_by_sku.get("coffee") == Decimal("3")
    assert delta.supply_in_by_sku.get("coffee") == Decimal("10")
    # book = 0 + 10 - 0 - 3 = 7; delta = actual0 - 7 = -7
    assert delta.warehouse_delta_by_sku.get("coffee") == Decimal("-7")


def test_delta_port_reports_empty_unmatched_after_non_domain_truncate() -> None:
    """edge: import truncate → unmatched_products всегда ()."""
    port = _delta_case_with_unmatched("unknown-code")
    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR))
    assert delta is not None
    assert delta.unmatched_products == ()
    # transfer с empty lines всё равно может быть в refs после truncate-all
    assert any(ref.external_document_id == "bad" for ref in delta.transfer_refs)


def test_delta_port_propagates_ms_unavailable_blocker() -> None:
    port = _delta_case_with_import_error(MoySkladUnavailable("timeout"))
    with pytest.raises(MoySkladUnavailable, match="timeout"):
        asyncio.run(port.get_delta(_TECHNICIAN_ID, after=None, until=_ANCHOR))


def test_delta_service_computes_when_latest_delta_missing() -> None:
    """inventory без _latest_delta: get_delta считает окно через compute-on-demand."""
    repository = _repository_with_two_inventories()
    warehouse = repository.get(_TECHNICIAN_ID)
    assert warehouse.latest_warehouse_delta() is None

    @dataclass(slots=True)
    class NoOpImporter(ImportTechnicianWarehouseTransfers):
        calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

        async def execute(
            self,
            technician_id: TechnicianId,
            *,
            anchor_at: datetime,
        ) -> TechnicianWarehouseImportResult:
            self.calls.append((technician_id, anchor_at))
            return TechnicianWarehouseImportResult(
                imported=0,
                updated=0,
                voided=0,
                ignored=0,
                skipped_unresolved=0,
                truncated_non_domain=0,
                transfer_refs=(),
                unmatched_products=(),
            )

    importer = NoOpImporter(
        reader=FakeTransferReader(),
        catalog_base_quantity_resolver=_catalog_resolver(),
        executor=TechnicianWarehouseExecutor(repository=repository),
        supply_store_codes=("main",),
        lookback_days=60,
    )
    port = TechnicianWarehouseDeltaService(importer=importer, executor=importer.executor)

    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR))

    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]
    assert delta is not None
    assert delta.warehouse_delta_by_sku == {"coffee": Decimal("-2")}
    assert delta.warehouse_inventory_id == "inv-current"


def test_get_delta_default_calls_importer() -> None:
    port, importer = _delta_case_with_two_inventories()
    delta = asyncio.run(port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR))
    assert delta is not None
    assert importer.calls == [(_TECHNICIAN_ID, _ANCHOR)]


def test_get_delta_skip_import_does_not_call_importer() -> None:
    port, importer = _delta_case_with_two_inventories()
    delta = asyncio.run(
        port.get_delta(_TECHNICIAN_ID, after=_PREVIOUS, until=_ANCHOR, skip_import=True),
    )
    assert delta is not None
    assert importer.calls == []
    assert delta.transfer_refs == ()
    assert delta.unmatched_products == ()
