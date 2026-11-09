from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.master_data import MachineKind
from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.planogram import MicromarketPlanogram
from src.application.micromarket_loading.ports import (
    CopiedMicromarketInventoryForm,
    MachineKindLookup,
    MicromarketAssemblyOrderStore,
    MicromarketDeviceStockStore,
    MicromarketInventoryFormFactory,
    MicromarketInventoryFormMode,
    MicromarketInventoryFormRegistry,
    MicromarketInventoryFormsConfig,
    MicromarketPlanogramStore,
    MicromarketSaleForReplay,
    MicromarketSalesAfterPort,
    MicromarketSupplyOrderStore,
    MicromarketWarehouseStockSnapshotPort,
    PendingMicromarketInventStore,
    RegisteredMicromarketInventoryForm,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
    SupplyOrderCategoryFactsSnapshotPort,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    JOURNAL_CAPACITY,
    ShopListLastSucceededSnapshot,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
)
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactRow,
    SupplyOrderCategoryFactsSnapshot,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    MicromarketAssemblyOrder,
)
from src.domain.micromarket_loading.events import MicromarketStockEvent
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent
from src.domain.micromarket_loading.supply_order import MicromarketSupplyOrder


@beartype
@dataclass(slots=True)
class InMemoryMicromarketDeviceStockStore(MicromarketDeviceStockStore):
    _streams: dict[str, list[MicromarketStockEvent]] = field(default_factory=dict)

    @beartype
    def load(self, machine_code: str) -> MicromarketDeviceStock | None:
        stream = self._streams.get(machine_code)
        if stream is None:
            return None
        return MicromarketDeviceStock.rehydrate(machine_code=machine_code, events=stream)

    @beartype
    def save(self, stock: MicromarketDeviceStock) -> None:
        stream = self._streams.setdefault(stock.machine_code, [])
        if len(stream) != stock.loaded_version:
            raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)
        pending = stock.pull_events()
        if not pending:
            return
        stream.extend(pending)

    @beartype
    def list_events(self, machine_code: str) -> Sequence[MicromarketStockEvent]:
        return tuple(self._streams.get(machine_code, ()))


@beartype
@dataclass(slots=True)
class InMemoryMicromarketPlanogramStore(MicromarketPlanogramStore):
    _by_machine: dict[str, MicromarketPlanogram] = field(default_factory=dict)

    @beartype
    def get(self, machine_code: str) -> MicromarketPlanogram | None:
        return self._by_machine.get(machine_code)

    @beartype
    def upsert(self, planogram: MicromarketPlanogram) -> None:
        self._by_machine[planogram.machine_code] = planogram

    @beartype
    def list_all(self) -> Sequence[MicromarketPlanogram]:
        return tuple(self._by_machine.values())


@beartype
@dataclass(slots=True)
class InMemoryMicromarketSupplyOrderStore(MicromarketSupplyOrderStore):
    _by_id: dict[str, MicromarketSupplyOrder] = field(default_factory=dict)

    @beartype
    def save(self, order: MicromarketSupplyOrder) -> None:
        self._by_id[order.order_id] = order

    @beartype
    def get(self, order_id: str) -> MicromarketSupplyOrder | None:
        return self._by_id.get(order_id)

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[MicromarketSupplyOrder]:
        ordered = sorted(self._by_id.values(), key=lambda row: row.created_at, reverse=True)
        if limit is None:
            return tuple(ordered)
        return tuple(ordered[:limit])

    @beartype
    def delete(self, order_id: str) -> bool:
        if order_id not in self._by_id:
            return False
        del self._by_id[order_id]
        return True


@beartype
@dataclass(slots=True)
class InMemoryShopListPublishJournal(ShopListPublishJournal):
    _entries: list[ShopListPublishJournalEntry] = field(default_factory=list)

    @beartype
    def append(self, entry: ShopListPublishJournalEntry) -> None:
        self._entries.append(entry)
        overflow = len(self._entries) - JOURNAL_CAPACITY
        if overflow > 0:
            del self._entries[:overflow]

    @beartype
    def update_by_publication_id(
        self,
        publication_id: str,
        *,
        status: ShopListPublishJournalStatus,
        now: datetime,
        error_message: str = "",
    ) -> None:
        for index, entry in enumerate(self._entries):
            if entry.publication_id != publication_id:
                continue
            self._entries[index] = ShopListPublishJournalEntry(
                publication_id=entry.publication_id,
                machine_code=entry.machine_code,
                status=status,
                created_at=entry.created_at,
                updated_at=now,
                error_message=error_message,
                trigger=entry.trigger,
                effects=entry.effects,
                intended_lines=entry.intended_lines,
                baseline_lines=entry.baseline_lines,
            )
            return

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[ShopListPublishJournalEntry]:
        ordered = sorted(self._entries, key=lambda row: row.created_at, reverse=True)
        if limit is None:
            return tuple(ordered)
        return tuple(ordered[:limit])


@beartype
@dataclass(slots=True)
class InMemoryShopListLastSucceededSnapshotStore(ShopListLastSucceededSnapshotStore):
    _by_machine: dict[str, ShopListLastSucceededSnapshot] = field(default_factory=dict)

    @beartype
    def get(self, machine_code: str) -> ShopListLastSucceededSnapshot | None:
        return self._by_machine.get(machine_code)

    @beartype
    def upsert(self, snapshot: ShopListLastSucceededSnapshot) -> None:
        self._by_machine[snapshot.machine_code] = snapshot


_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class InMemoryMicromarketAssemblyOrderStore(MicromarketAssemblyOrderStore):
    _by_id: dict[str, MicromarketAssemblyOrder] = field(default_factory=dict)

    @beartype
    def get(self, order_id: str) -> MicromarketAssemblyOrder | None:
        return self._by_id.get(order_id)

    @beartype
    def list_open(self) -> tuple[MicromarketAssemblyOrder, ...]:
        return tuple(
            order for order in self._by_id.values() if order.status is AssemblyOrderStatus.OPEN
        )

    @beartype
    def list_open_for_machine(self, machine_code: str) -> tuple[MicromarketAssemblyOrder, ...]:
        return tuple(order for order in self.list_open() if order.machine_code == machine_code)

    @beartype
    def save(self, order: MicromarketAssemblyOrder) -> None:
        self._by_id[order.order_id] = order


@beartype
@dataclass(slots=True)
class InMemoryPendingMicromarketInventStore(PendingMicromarketInventStore):
    _by_machine: dict[str, PendingMicromarketInvent] = field(default_factory=dict)

    @beartype
    def get_for_machine(self, machine_code: str) -> PendingMicromarketInvent | None:
        return self._by_machine.get(machine_code)

    @beartype
    def save(self, pending: PendingMicromarketInvent) -> None:
        self._by_machine[pending.machine_code] = pending

    @beartype
    def clear(self, machine_code: str) -> None:
        self._by_machine.pop(machine_code, None)


@beartype
@dataclass(slots=True)
class InMemoryMicromarketWarehouseStockSnapshotStore(MicromarketWarehouseStockSnapshotPort):
    _snapshot: MainWarehouseStockSnapshot | None = None

    @beartype
    def get(self) -> MainWarehouseStockSnapshot | None:
        return self._snapshot

    @beartype
    def replace(self, snapshot: MainWarehouseStockSnapshot) -> None:
        self._snapshot = MainWarehouseStockSnapshot(
            warehouse_id=snapshot.warehouse_id,
            refreshed_at=snapshot.refreshed_at,
            qty_by_catalog_code=dict(snapshot.qty_by_catalog_code),
        )

    @beartype
    def apply_delta(self, *, deltas: Mapping[str, Decimal]) -> None:
        if self._snapshot is None:
            _LOGGER.warning("micromarket_warehouse_stock_delta_without_snapshot")
            return
        qty = dict(self._snapshot.qty_by_catalog_code)
        for code, delta in deltas.items():
            if not code:
                continue
            current = qty.get(code, Decimal("0"))
            if code not in qty:
                _LOGGER.warning(
                    "micromarket_warehouse_stock_delta_missing_code",
                    extra={"catalog_code": code},
                )
            next_qty = current + delta
            if next_qty < 0:
                _LOGGER.warning(
                    "micromarket_warehouse_stock_delta_clamped",
                    extra={"catalog_code": code, "raw": str(next_qty)},
                )
                next_qty = Decimal("0")
            qty[code] = next_qty
        self._snapshot = MainWarehouseStockSnapshot(
            warehouse_id=self._snapshot.warehouse_id,
            refreshed_at=self._snapshot.refreshed_at,
            qty_by_catalog_code=qty,
        )


@beartype
@dataclass(slots=True)
class InMemorySupplyOrderCategoryFactsSnapshotStore(SupplyOrderCategoryFactsSnapshotPort):
    _snapshot: SupplyOrderCategoryFactsSnapshot | None = None

    @beartype
    def get(self) -> SupplyOrderCategoryFactsSnapshot | None:
        return self._snapshot

    @beartype
    def replace(self, snapshot: SupplyOrderCategoryFactsSnapshot) -> None:
        self._snapshot = SupplyOrderCategoryFactsSnapshot(
            refreshed_at=snapshot.refreshed_at,
            facts_by_catalog_code={
                code: SupplyOrderCategoryFactRow(
                    folder_ancestor_ids=row.folder_ancestor_ids,
                    shelf_life_days=row.shelf_life_days,
                )
                for code, row in snapshot.facts_by_catalog_code.items()
            },
        )


@beartype
@dataclass(frozen=True, slots=True)
class StaticMachineKindLookup(MachineKindLookup):
    _kinds: dict[str, MachineKind]

    @beartype
    def kind_of(self, machine_code: str) -> MachineKind | None:
        return self._kinds.get(machine_code)


@beartype
@dataclass(slots=True)
class InMemoryMicromarketSalesAfter(MicromarketSalesAfterPort):
    """Test double: tuples (sale_source_id, product_code, qty, occurred_at)."""

    sales: Sequence[tuple[str, str, Decimal, datetime]]

    @beartype
    def query(
        self,
        machine_code: str,
        after: datetime,
    ) -> Sequence[MicromarketSaleForReplay]:
        del machine_code
        return tuple(
            MicromarketSaleForReplay(
                sale_source_id=sale_source_id,
                product_code=product_code,
                qty=qty,
                occurred_at=occurred_at,
            )
            for sale_source_id, product_code, qty, occurred_at in self.sales
            if occurred_at > after
        )


@beartype
@dataclass(slots=True)
class InMemoryMicromarketInventoryFormRegistry(MicromarketInventoryFormRegistry):
    _by_key: dict[
        tuple[str, MicromarketInventoryFormMode, str],
        RegisteredMicromarketInventoryForm,
    ] = field(default_factory=dict)

    @beartype
    def get(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
    ) -> RegisteredMicromarketInventoryForm | None:
        return self._by_key.get((machine_code, mode, fingerprint))

    @beartype
    def put(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
        *,
        form_id: str,
        form_url: str,
    ) -> None:
        self._by_key[(machine_code, mode, fingerprint)] = RegisteredMicromarketInventoryForm(
            form_id=form_id,
            form_url=form_url,
        )


@beartype
@dataclass(slots=True)
class StubMicromarketInventoryFormFactory(MicromarketInventoryFormFactory):
    form_id: str = "mm-form-1"
    form_url: str = "https://forms.example/mm-form-1"

    @beartype
    def copy_template_and_build_questions(
        self,
        *,
        template_id: str,
        pages: Sequence[InventoryFormPage],
        product_names: Mapping[str, str],
        qty_max: int,
    ) -> CopiedMicromarketInventoryForm:
        del template_id, pages, product_names, qty_max
        return CopiedMicromarketInventoryForm(form_id=self.form_id, form_url=self.form_url)


@beartype
@dataclass(slots=True)
class StubMicromarketInventoryFormsConfig(MicromarketInventoryFormsConfig):
    @beartype
    def require_micromarket_inventory_forms(self) -> None:
        return None

    @beartype
    def require_micromarket_inventory_now(self) -> None:
        return None
