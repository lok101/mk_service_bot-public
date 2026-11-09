from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.micromarket_loading.need_sheet import NeedRow, need_rows_xlsx
from src.application.micromarket_loading.ports import (
    MicromarketSupplyOrderStore,
    SupplyOrderCategoryFactsPort,
    SupplyOrderDemandForecastPort,
)
from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    classify_supply_order_product,
    index_category_facts,
)
from src.application.product_identity.ports import DomainProductStore, ProcurementMirrorStore
from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
    SupplyOrderLineCategory,
)

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class LiveNeedLine:
    product_code: str
    need_qty: Decimal
    shelf_qty: Decimal
    target_qty: Decimal
    name: str = ""


@beartype
@dataclass(frozen=True, slots=True)
class LiveNeedMachine:
    machine_id: str
    lines: tuple[LiveNeedLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderEmptySelection:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderNoPositiveNeed:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderNotFound:
    order_id: str


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderProductsNotLinked:
    items: tuple[tuple[str, str], ...]


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderMissingShelfLife:
    items: tuple[tuple[str, str], ...]


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderMsUnavailable:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderInvalidArrival:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class SupplyOrderCreated:
    order: MicromarketSupplyOrder
    xlsx: bytes
    forecast_unavailable_items: tuple[tuple[str, str], ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class ResolvedNeedLine:
    product_code: str
    need_qty: Decimal
    need_from_live: bool


@beartype
def supply_order_need_rows(order: MicromarketSupplyOrder) -> tuple[NeedRow, ...]:
    totals: dict[str, Decimal] = {}
    names: dict[str, str] = {}
    suppliers: dict[str, str | None] = {}
    prices: dict[str, Decimal | None] = {}
    packages: dict[str, Decimal | None] = {}
    supplier_names: dict[str, str | None] = {}
    for machine in order.machines:
        for line in machine.lines:
            totals[line.product_code] = totals.get(line.product_code, Decimal("0")) + line.need_qty
            if line.name and (line.product_code not in names or not names.get(line.product_code)):
                names[line.product_code] = line.name
            if line.product_code not in suppliers:
                suppliers[line.product_code] = line.supplier_name
                prices[line.product_code] = line.last_buy_price
                packages[line.product_code] = line.package_quantity
                supplier_names[line.product_code] = line.supplier_product_name
    rows: list[NeedRow] = []
    for code in sorted(totals):
        qty = totals[code]
        if qty == 0:
            continue
        rows.append(
            NeedRow(
                product_code=code,
                name=names.get(code, ""),
                need_qty=qty,
                supplier_name=suppliers.get(code),
                last_buy_price=prices.get(code),
                package_quantity=packages.get(code),
                supplier_product_name=supplier_names.get(code),
            ),
        )
    return tuple(rows)


@beartype
@dataclass(slots=True)
class CreateMicromarketSupplyOrder:
    store: MicromarketSupplyOrderStore
    clock: Callable[[], datetime]
    products: DomainProductStore
    category_facts: SupplyOrderCategoryFactsPort
    snacks_folder_id: str
    ready_meals_folder_id: str
    shelf_life_days_threshold: int
    forecast: SupplyOrderDemandForecastPort
    mirrors: ProcurementMirrorStore | None = None

    @beartype
    def execute(
        self,
        *,
        machines: Sequence[LiveNeedMachine],
        expected_arrival_at: datetime | None,
    ) -> (
        SupplyOrderCreated
        | SupplyOrderEmptySelection
        | SupplyOrderNoPositiveNeed
        | SupplyOrderProductsNotLinked
        | SupplyOrderMissingShelfLife
        | SupplyOrderMsUnavailable
        | SupplyOrderInvalidArrival
    ):
        now = self.clock()
        if expected_arrival_at is None or expected_arrival_at <= now:
            _LOGGER.info("micromarket_supply_order_rejected_invalid_arrival")
            return SupplyOrderInvalidArrival()
        if not machines:
            return SupplyOrderEmptySelection()
        positive_codes: dict[str, str] = {}
        for machine in machines:
            for line in machine.lines:
                if line.need_qty <= 0:
                    continue
                if line.product_code not in positive_codes:
                    positive_codes[line.product_code] = line.name
        if not positive_codes:
            return SupplyOrderNoPositiveNeed()

        unlinked: list[tuple[str, str]] = []
        catalog_by_code: dict[str, str] = {}
        for product_code, display_name in sorted(positive_codes.items()):
            product = self.products.get_by_number(product_code)
            raw_catalog = product.catalog_code if product is not None else None
            catalog = raw_catalog.strip() if raw_catalog else ""
            if product is None or not catalog:
                unlinked.append((product_code, display_name or product_code))
                continue
            catalog_by_code[product_code] = catalog
        if unlinked:
            _LOGGER.info(
                "micromarket_supply_order_rejected_unlinked",
                extra={"unlinked_count": len(unlinked)},
            )
            return SupplyOrderProductsNotLinked(items=tuple(unlinked))

        unique_catalogs = tuple(sorted(set(catalog_by_code.values())))
        fetched = self.category_facts.fetch_by_catalog_codes(unique_catalogs)
        if isinstance(fetched, SupplyOrderCategoryFactsFetchFailed):
            _LOGGER.info("micromarket_supply_order_ms_unavailable")
            return SupplyOrderMsUnavailable()
        facts_by_catalog = index_category_facts(fetched)

        counts = {
            "cat1": 0,
            "cat2": 0,
            "cat3": 0,
            "ignored": 0,
            "blocked_missing_days": 0,
        }
        category_by_product: dict[str, SupplyOrderLineCategory] = {}
        missing_days: list[tuple[str, str]] = []
        for product_code, catalog in catalog_by_code.items():
            facts = facts_by_catalog.get(catalog)
            if facts is None:
                counts["ignored"] += 1
                continue
            classified = classify_supply_order_product(
                facts,
                snacks_folder_id=self.snacks_folder_id,
                ready_meals_folder_id=self.ready_meals_folder_id,
                shelf_life_days_threshold=self.shelf_life_days_threshold,
            )
            if classified.kind == "snack":
                counts["cat1"] += 1
                continue
            if classified.kind == "ignore":
                counts["ignored"] += 1
                continue
            if classified.kind == "missing_days":
                counts["blocked_missing_days"] += 1
                missing_days.append((product_code, positive_codes.get(product_code, product_code)))
                continue
            if classified.category is None:
                counts["ignored"] += 1
                continue
            if classified.category == 2:
                counts["cat2"] += 1
            else:
                counts["cat3"] += 1
            category_by_product[product_code] = classified.category

        _LOGGER.info(
            "micromarket_supply_order_category_counts",
            extra=counts,
        )
        if missing_days:
            _LOGGER.info(
                "micromarket_supply_order_rejected_missing_shelf_life",
                extra={"missing_count": len(missing_days)},
            )
            return SupplyOrderMissingShelfLife(items=tuple(sorted(missing_days)))

        snapshot_machines: list[MicromarketSupplyOrderMachine] = []
        line_count = 0
        forecast_count = 0
        fallback_count = 0
        unavailable: list[tuple[str, str]] = []
        seen_unavailable: set[str] = set()
        for machine in machines:
            positive: list[MicromarketSupplyOrderLine] = []
            for line in machine.lines:
                if line.need_qty <= 0:
                    continue
                category = category_by_product.get(line.product_code)
                if category is None:
                    continue
                catalog = catalog_by_code[line.product_code]
                mirror = self.mirrors.get(catalog) if self.mirrors is not None else None
                gap = line.need_qty
                forecast = self.forecast.forecast_qty(
                    machine_id=machine.machine_id,
                    product_code=line.product_code,
                    category=category,
                    horizon_start=now,
                    horizon_end=expected_arrival_at,
                    shelf_qty=line.shelf_qty,
                    target_qty=line.target_qty,
                )
                if forecast is None:
                    fallback_count += 1
                    need_qty = gap
                    forecast_qty = Decimal("0")
                    if line.product_code not in seen_unavailable:
                        seen_unavailable.add(line.product_code)
                        unavailable.append(
                            (line.product_code, line.name or line.product_code),
                        )
                else:
                    forecast_count += 1
                    need_qty = gap + forecast
                    forecast_qty = forecast
                positive.append(
                    MicromarketSupplyOrderLine(
                        product_code=line.product_code,
                        need_qty=need_qty,
                        category=category,
                        name=line.name,
                        supplier_name=mirror.supplier_name if mirror is not None else None,
                        last_buy_price=mirror.last_buy_price if mirror is not None else None,
                        package_quantity=mirror.package_quantity if mirror is not None else None,
                        supplier_product_name=(
                            mirror.supplier_product_name if mirror is not None else None
                        ),
                        gap_qty=gap,
                        forecast_qty=forecast_qty,
                    ),
                )
            if not positive:
                continue
            line_count += len(positive)
            snapshot_machines.append(
                MicromarketSupplyOrderMachine(
                    machine_id=machine.machine_id,
                    lines=tuple(positive),
                ),
            )
        if not snapshot_machines:
            return SupplyOrderNoPositiveNeed()
        order = MicromarketSupplyOrder(
            order_id=str(uuid.uuid4()),
            created_at=now,
            expected_arrival_at=expected_arrival_at,
            machines=tuple(snapshot_machines),
        )
        self.store.save(order)
        xlsx = need_rows_xlsx(
            supply_order_need_rows(order),
            expected_arrival_at=order.expected_arrival_at,
        )
        _LOGGER.info(
            "micromarket_supply_order_created",
            extra={
                "order_id": order.order_id,
                "machine_count": len(order.machines),
                "line_count": line_count,
                "forecast_count": forecast_count,
                "fallback_count": fallback_count,
            },
        )
        return SupplyOrderCreated(
            order=order,
            xlsx=xlsx,
            forecast_unavailable_items=tuple(sorted(unavailable)),
        )


@beartype
@dataclass(slots=True)
class ListMicromarketSupplyOrders:
    store: MicromarketSupplyOrderStore

    @beartype
    def execute(self, *, limit: int | None = None) -> tuple[MicromarketSupplyOrder, ...]:
        return tuple(self.store.list_newest(limit=limit))


@beartype
@dataclass(slots=True)
class DownloadMicromarketSupplyOrder:
    store: MicromarketSupplyOrderStore

    @beartype
    def execute(self, order_id: str) -> bytes | SupplyOrderNotFound:
        order = self.store.get(order_id)
        if order is None:
            return SupplyOrderNotFound(order_id=order_id)
        payload = need_rows_xlsx(
            supply_order_need_rows(order),
            expected_arrival_at=order.expected_arrival_at,
        )
        _LOGGER.info(
            "micromarket_supply_order_downloaded",
            extra={"order_id": order_id},
        )
        return payload


@beartype
@dataclass(slots=True)
class DeleteMicromarketSupplyOrder:
    store: MicromarketSupplyOrderStore

    @beartype
    def execute(self, order_id: str) -> None | SupplyOrderNotFound:
        deleted = self.store.delete(order_id)
        if not deleted:
            return SupplyOrderNotFound(order_id=order_id)
        _LOGGER.info(
            "micromarket_supply_order_deleted",
            extra={"order_id": order_id},
        )
        return None


@beartype
@dataclass(slots=True)
class ResolveLoadingNeed:
    store: MicromarketSupplyOrderStore

    @beartype
    def execute(
        self,
        *,
        machine_id: str,
        live_need_by_code: Mapping[str, Decimal],
    ) -> tuple[ResolvedNeedLine, ...]:
        order_lines = _latest_order_lines_for_machine(self.store, machine_id)
        resolved: list[ResolvedNeedLine] = []
        for product_code, live_qty in live_need_by_code.items():
            ordered = order_lines.get(product_code)
            if ordered is not None:
                resolved.append(
                    ResolvedNeedLine(
                        product_code=product_code,
                        need_qty=ordered,
                        need_from_live=False,
                    ),
                )
            else:
                resolved.append(
                    ResolvedNeedLine(
                        product_code=product_code,
                        need_qty=live_qty,
                        need_from_live=True,
                    ),
                )
        return tuple(resolved)


@beartype
def _latest_order_lines_for_machine(
    store: MicromarketSupplyOrderStore,
    machine_id: str,
) -> dict[str, Decimal]:
    for order in store.list_newest():
        for machine in order.machines:
            if machine.machine_id != machine_id:
                continue
            return {line.product_code: line.need_qty for line in machine.lines}
    return {}
