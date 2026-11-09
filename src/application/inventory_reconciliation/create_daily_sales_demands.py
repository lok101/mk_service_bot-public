from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.form_submissions import NonRetryableOutboxError
from src.application.inventory_reconciliation.ms_registrar_ports import (
    DailySalesDemandRegistrar,
    RegistrarPermanentError,
    RegistrarTransientError,
    StockDocumentLine,
)
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.inventory_reconciliation.sellable_assortment_ports import (
    SellableProductCodeCatalog,
)
from src.domain.machine_sales import MachineSale, SaleKind

_LOGGER = logging.getLogger(__name__)
_ALLOWED_KINDS: frozenset[SaleKind] = frozenset({"snack"})
_EXPECTED_SKIP_KINDS: frozenset[SaleKind] = frozenset({"coffee", "micromarket"})


class IngestCursorNotReady(Exception):
    """Global sales ingest cursor is behind day_end; outbox should retry."""

    @beartype
    def __init__(self, message: str) -> None:
        if not message:
            raise ValueError("message must not be empty")
        super().__init__(message)


class SellableCatalogNotReady(Exception):
    """Sellable assortment snapshot missing / no MS products; outbox should retry."""

    @beartype
    def __init__(self, message: str) -> None:
        if not message:
            raise ValueError("message must not be empty")
        super().__init__(message)


class UnresolvedSellableCodesError(NonRetryableOutboxError):
    @beartype
    def __init__(self, unresolved: frozenset[tuple[str, str]]) -> None:
        if not unresolved:
            raise ValueError("unresolved must not be empty")
        self.unresolved = unresolved
        codes = sorted({code for _, code in unresolved})
        joined = ", ".join(codes)
        super().__init__(
            f"Sellable assortment missing codes ({len(codes)}): {joined}. "
            "Fix product_catalog / BOM, then outbox_admin requeue.",
        )


class UnresolvedStoreCodesError(NonRetryableOutboxError):
    @beartype
    def __init__(self, codes: frozenset[str]) -> None:
        if not codes:
            raise ValueError("codes must not be empty")
        self.codes = codes
        joined = ", ".join(sorted(codes))
        super().__init__(
            f"Moysklad store missing for warehouse codes ({len(codes)}): {joined}. "
            "Fix store codes in MS / mapping, then outbox_admin requeue.",
        )


class DailySalesDemandTransientError(Exception):
    @beartype
    def __init__(self, warehouse_codes: frozenset[str]) -> None:
        if not warehouse_codes:
            raise ValueError("warehouse_codes must not be empty")
        self.warehouse_codes = warehouse_codes
        joined = ", ".join(sorted(warehouse_codes))
        super().__init__(
            f"Transient MoySklad errors for warehouse codes ({len(warehouse_codes)}): {joined}."
        )


@beartype
def price_to_kop(price: Decimal) -> int:
    return int((price * 100).to_integral_value(rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class _MachineDemandCandidate:
    warehouse_code: str
    kind: SaleKind
    lines: list[StockDocumentLine]
    sales_channel_id: UUID


@beartype
@dataclass(frozen=True, slots=True)
class CreateDailySalesDemands:
    sales_store: MachineSalesStore
    registrar: DailySalesDemandRegistrar
    sellable_catalog: SellableProductCodeCatalog
    display_timezone: str
    project_id: UUID
    snack_sales_channel_id: UUID

    @beartype
    async def execute(self, *, sales_day: date) -> None:
        tz = ZoneInfo(self.display_timezone)
        day_start = datetime.combine(sales_day, time.min, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        document_moment = datetime.combine(sales_day, time(23, 55), tzinfo=tz)

        cursor = self.sales_store.load_global_cursor()
        if cursor is None or cursor < day_end:
            raise IngestCursorNotReady(
                f"global_cursor={cursor!s} is not ready for day_end={day_end.isoformat()}"
            )

        if not self.sellable_catalog.ready():
            raise SellableCatalogNotReady(
                f"sellable catalog is not ready for sales_day={sales_day.isoformat()}"
            )

        sales = self.sales_store.find_in_global_window(opened_at=day_start, closed_at=day_end)
        by_warehouse: dict[str, list[MachineSale]] = defaultdict(list)
        for sale in sales:
            warehouse_code = sale.machine_code or sale.machine_id.value
            by_warehouse[warehouse_code].append(sale)

        candidates: list[_MachineDemandCandidate] = []
        skipped_kind = 0
        for warehouse_code, machine_sales in by_warehouse.items():
            kinds = {sale.sale_kind for sale in machine_sales}
            if len(kinds) != 1 or next(iter(kinds)) not in _ALLOWED_KINDS:
                skipped_kind += 1
                sole = next(iter(kinds)) if len(kinds) == 1 else None
                log_extra = {
                    "warehouse_code": warehouse_code,
                    "sale_kinds": sorted(kinds),
                    "sales_day": sales_day.isoformat(),
                }
                if sole in _EXPECTED_SKIP_KINDS:
                    _LOGGER.info(
                        "daily_sales_demand skip machine: non_snack_sale_kind",
                        extra=log_extra,
                    )
                else:
                    _LOGGER.error(
                        "daily_sales_demand skip machine: invalid sale_kind",
                        extra=log_extra,
                    )
                continue

            kind = next(iter(kinds))
            qty_by_key: dict[tuple[str, int], Decimal] = defaultdict(lambda: Decimal("0"))
            for sale in machine_sales:
                if sale.price is None:
                    _LOGGER.warning(
                        "daily_sales_demand skip line: price is None",
                        extra={
                            "warehouse_code": warehouse_code,
                            "product_code": sale.product_code,
                            "source_id": sale.source_id,
                            "sales_day": sales_day.isoformat(),
                        },
                    )
                    continue
                price_kop = price_to_kop(sale.price)
                qty_by_key[(sale.product_code, price_kop)] += sale.quantity

            if not qty_by_key:
                continue

            lines = [
                StockDocumentLine(product_code=product_code, quantity=quantity, price_kop=price_kop)
                for (product_code, price_kop), quantity in qty_by_key.items()
            ]
            channel = self.snack_sales_channel_id
            candidates.append(
                _MachineDemandCandidate(
                    warehouse_code=warehouse_code,
                    kind=kind,
                    lines=lines,
                    sales_channel_id=channel,
                )
            )

        unresolved: set[tuple[str, str]] = set()
        dirty_warehouses: set[str] = set()
        for candidate in candidates:
            for line in candidate.lines:
                if not self.sellable_catalog.contains(line.product_code):
                    unresolved.add((candidate.warehouse_code, line.product_code))
                    dirty_warehouses.add(candidate.warehouse_code)

        created_machines = 0
        skipped_stores: set[str] = set()
        transient_warehouses: set[str] = set()
        for candidate in candidates:
            if candidate.warehouse_code in dirty_warehouses:
                continue
            try:
                await self.registrar.register_daily_sales_demand(
                    warehouse_code=candidate.warehouse_code,
                    lines=candidate.lines,
                    moment=document_moment,
                    sales_day=sales_day,
                    sales_channel_id=candidate.sales_channel_id,
                    project_id=self.project_id,
                )
            except RegistrarPermanentError as exc:
                skipped_stores.add(candidate.warehouse_code)
                _LOGGER.error(
                    "daily_sales_demand skip machine: permanent registrar error",
                    extra={
                        "warehouse_code": candidate.warehouse_code,
                        "sales_day": sales_day.isoformat(),
                        "error": str(exc),
                    },
                )
                continue
            except RegistrarTransientError as exc:
                transient_warehouses.add(candidate.warehouse_code)
                _LOGGER.warning(
                    "daily_sales_demand transient registrar error",
                    extra={
                        "warehouse_code": candidate.warehouse_code,
                        "sales_day": sales_day.isoformat(),
                        "error": str(exc),
                    },
                )
                continue
            created_machines += 1

        if transient_warehouses:
            _LOGGER.warning(
                "daily_sales_demand transient tail",
                extra={
                    "sales_day": sales_day.isoformat(),
                    "transient_warehouse_codes": sorted(transient_warehouses),
                    "created_machines": created_machines,
                    "skipped_kind": skipped_kind,
                    "skipped_stores_count": len(skipped_stores),
                    "unresolved_sellable_count": len(unresolved),
                },
            )
            raise DailySalesDemandTransientError(frozenset(transient_warehouses))

        if unresolved:
            unresolved_frozen = frozenset(unresolved)
            _LOGGER.error(
                "daily_sales_demand unresolved sellable codes",
                extra={
                    "sales_day": sales_day.isoformat(),
                    "unresolved_sellable_codes": sorted(unresolved_frozen),
                    "unresolved_code_count": len({code for _, code in unresolved_frozen}),
                    "created_machines": created_machines,
                    "skipped_kind": skipped_kind,
                },
            )
            raise UnresolvedSellableCodesError(unresolved_frozen)

        if skipped_stores:
            raise UnresolvedStoreCodesError(frozenset(skipped_stores))

        _LOGGER.info(
            "daily_sales_demand completed",
            extra={
                "sales_day": sales_day.isoformat(),
                "candidate_count": len(candidates),
                "created_machines": created_machines,
                "skipped_kind": skipped_kind,
            },
        )
