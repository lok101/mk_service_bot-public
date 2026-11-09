from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.master_data import MachineKind
from src.application.micromarket_loading.pricing_stores import (
    MicromarketPriceChangeJournalEntry,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListLastSucceededSnapshot,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
)
from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)
from src.application.micromarket_loading.supply_order_category_snapshot import (
    SupplyOrderCategoryFactsSnapshot,
)
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.assembly_order import MicromarketAssemblyOrder
from src.domain.micromarket_loading.events import MicromarketStockEvent
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent
from src.domain.micromarket_loading.supply_order import MicromarketSupplyOrder
from src.domain.micromarket_pricing.formula import MicromarketPricingRules

if TYPE_CHECKING:
    from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
    from src.application.micromarket_loading.planogram import MicromarketPlanogram

MicromarketInventoryFormMode = Literal["now", "as_of"]


@runtime_checkable
class MicromarketDeviceStockStore(Protocol):
    @beartype
    def load(self, machine_code: str) -> MicromarketDeviceStock | None: ...

    @beartype
    def save(self, stock: MicromarketDeviceStock) -> None: ...

    @beartype
    def list_events(self, machine_code: str) -> Sequence[MicromarketStockEvent]: ...


@runtime_checkable
class MachineKindLookup(Protocol):
    @beartype
    def kind_of(self, machine_code: str) -> MachineKind | None: ...


@runtime_checkable
class MicromarketPlanogramStore(Protocol):
    @beartype
    def get(self, machine_code: str) -> MicromarketPlanogram | None: ...

    @beartype
    def upsert(self, planogram: MicromarketPlanogram) -> None: ...

    @beartype
    def list_all(self) -> Sequence[MicromarketPlanogram]: ...


@runtime_checkable
class ShopListPublishJournal(Protocol):
    @beartype
    def append(self, entry: ShopListPublishJournalEntry) -> None: ...

    @beartype
    def update_by_publication_id(
        self,
        publication_id: str,
        *,
        status: ShopListPublishJournalStatus,
        now: datetime,
        error_message: str = "",
    ) -> None: ...

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[ShopListPublishJournalEntry]: ...


@runtime_checkable
class ShopListLastSucceededSnapshotStore(Protocol):
    """Baseline intended snapshot per machine after last succeeded publish."""

    @beartype
    def get(self, machine_code: str) -> ShopListLastSucceededSnapshot | None: ...

    @beartype
    def upsert(self, snapshot: ShopListLastSucceededSnapshot) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketSaleForReplay:
    sale_source_id: str
    product_code: str
    qty: Decimal
    occurred_at: datetime


@runtime_checkable
class MicromarketSalesAfterPort(Protocol):
    """Sales for inventory replay (occurred_at > after)."""

    @beartype
    def query(
        self,
        machine_code: str,
        after: datetime,
    ) -> Sequence[MicromarketSaleForReplay]: ...


@runtime_checkable
class VisitFinalizedForDayPort(Protocol):
    """True when MaintenanceCompleted exists for machine in the operational day."""

    @beartype
    def is_finalized(self, machine_code: str, checked_at: datetime) -> bool: ...


@runtime_checkable
class EnsureOpenVisitTaskPort(Protocol):
    """Composition-facing ensure of an open working VisitTask; returns visit_id.

    Implemented outside application/micromarket_loading (no BC edge to service_visits).
    ``source`` is a stable string token (e.g. micromarket_loading, field_activity).
    """

    @beartype
    def ensure_open(
        self,
        *,
        machine_code: str,
        at: datetime,
        source: str,
        loading_order_id: str | None = None,
    ) -> str: ...


@runtime_checkable
class CompleteOpenVisitTaskPort(Protocol):
    """Composition-facing complete of an open VisitTask for machine/ops day.

    Implemented outside application/micromarket_loading (no BC edge to service_visits).
    Returns completed ``visit_id``, or ``None`` when no open visit matched.
    """

    @beartype
    def complete_open(
        self,
        *,
        machine_code: str,
        at: datetime,
        source: str,
    ) -> str | None: ...


@runtime_checkable
class EnqueuePostVisitSqueezePort(Protocol):
    """Enqueue post-visit squeeze (Load → publish → post invent) for a pending invent."""

    @beartype
    def enqueue(self, *, machine_code: str, inventory_id: str) -> None: ...


@runtime_checkable
class DetachVisitTaskOnLoadingRollbackPort(Protocol):
    """Composition-facing conditional detach of VisitTask after loading rollback.

    Implemented outside application/micromarket_loading (no BC edge to service_visits).
    """

    @beartype
    def detach(
        self,
        *,
        machine_code: str,
        at: datetime,
        visit_id: str | None,
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class RegisteredMicromarketInventoryForm:
    form_id: str
    form_url: str


@beartype
@dataclass(frozen=True, slots=True)
class CopiedMicromarketInventoryForm:
    form_id: str
    form_url: str


@runtime_checkable
class MicromarketInventoryFormRegistry(Protocol):
    @beartype
    def get(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
    ) -> RegisteredMicromarketInventoryForm | None: ...

    @beartype
    def put(
        self,
        machine_code: str,
        mode: MicromarketInventoryFormMode,
        fingerprint: str,
        *,
        form_id: str,
        form_url: str,
    ) -> None: ...


@runtime_checkable
class MicromarketInventoryFormFactory(Protocol):
    @beartype
    def copy_template_and_build_questions(
        self,
        *,
        template_id: str,
        pages: Sequence[InventoryFormPage],
        product_names: Mapping[str, str],
        qty_max: int,
    ) -> CopiedMicromarketInventoryForm: ...


@runtime_checkable
class MicromarketInventoryFormsConfig(Protocol):
    @beartype
    def require_micromarket_inventory_forms(self) -> None: ...

    @beartype
    def require_micromarket_inventory_now(self) -> None: ...


@runtime_checkable
class MicromarketSupplyOrderStore(Protocol):
    @beartype
    def save(self, order: MicromarketSupplyOrder) -> None: ...

    @beartype
    def get(self, order_id: str) -> MicromarketSupplyOrder | None: ...

    @beartype
    def list_newest(self, *, limit: int | None = None) -> Sequence[MicromarketSupplyOrder]: ...

    @beartype
    def delete(self, order_id: str) -> bool: ...


@runtime_checkable
class SupplyOrderCategoryFactsPort(Protocol):
    """Facts for supply-order classification (snapshot-backed after U1)."""

    @beartype
    def fetch_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Sequence[SupplyOrderCategoryProductFacts] | SupplyOrderCategoryFactsFetchFailed: ...


@runtime_checkable
class SupplyOrderCategoryFactsSnapshotPort(Protocol):
    """Mongo/in-memory snapshot of category facts refreshed by effects."""

    @beartype
    def get(self) -> SupplyOrderCategoryFactsSnapshot | None: ...

    @beartype
    def replace(self, snapshot: SupplyOrderCategoryFactsSnapshot) -> None: ...


@runtime_checkable
class SupplyOrderDemandForecastPort(Protocol):
    """Black-box demand forecast for supply-order Create (qty or unavailable)."""

    @beartype
    def forecast_qty(
        self,
        *,
        machine_id: str,
        product_code: str,
        category: Literal[2, 3],
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
    ) -> Decimal | None: ...


@runtime_checkable
class MicromarketWarehouseStockSnapshotPort(Protocol):
    """Main-warehouse stock snapshot for micromarket loading UI and launch gate."""

    @beartype
    def get(self) -> MainWarehouseStockSnapshot | None: ...

    @beartype
    def replace(self, snapshot: MainWarehouseStockSnapshot) -> None: ...

    @beartype
    def apply_delta(self, *, deltas: Mapping[str, Decimal]) -> None: ...


@runtime_checkable
class MicromarketAssemblyOrderStore(Protocol):
    """Persistence for micromarket fridge assembly orders (before MS move)."""

    @beartype
    def get(self, order_id: str) -> MicromarketAssemblyOrder | None: ...

    @beartype
    def list_open(self) -> tuple[MicromarketAssemblyOrder, ...]: ...

    @beartype
    def list_open_for_machine(self, machine_code: str) -> tuple[MicromarketAssemblyOrder, ...]: ...

    @beartype
    def save(self, order: MicromarketAssemblyOrder) -> None: ...


@runtime_checkable
class PendingMicromarketInventStore(Protocol):
    """Persistence for accepted invent ``now`` pending post-visit squeeze posting."""

    @beartype
    def get_for_machine(self, machine_code: str) -> PendingMicromarketInvent | None: ...

    @beartype
    def save(self, pending: PendingMicromarketInvent) -> None: ...

    @beartype
    def clear(self, machine_code: str) -> None: ...


@runtime_checkable
class MicromarketPricingRulesStore(Protocol):
    @beartype
    def get(self) -> MicromarketPricingRules | None: ...

    @beartype
    def save(self, rules: MicromarketPricingRules) -> None: ...


@runtime_checkable
class MicromarketProductMultiplierStore(Protocol):
    @beartype
    def get(self, product_code: str) -> Decimal | None: ...

    @beartype
    def list_all(self) -> Mapping[str, Decimal]: ...

    @beartype
    def upsert(self, product_code: str, multiplier: Decimal) -> None: ...

    @beartype
    def delete(self, product_code: str) -> None: ...


@runtime_checkable
class MicromarketMachineMultiplierStore(Protocol):
    @beartype
    def get(self, machine_id: str) -> Decimal | None: ...

    @beartype
    def list_all(self) -> Mapping[str, Decimal]: ...

    @beartype
    def upsert(self, machine_id: str, multiplier: Decimal) -> None: ...


@runtime_checkable
class MicromarketPriceChangeJournal(Protocol):
    @beartype
    def append(self, entry: MicromarketPriceChangeJournalEntry) -> None: ...

    @beartype
    def list_for_machine(
        self,
        machine_id: str,
        *,
        limit: int = 100,
    ) -> Sequence[MicromarketPriceChangeJournalEntry]: ...
