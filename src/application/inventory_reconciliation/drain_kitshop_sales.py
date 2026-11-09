from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancyStore,
    rebuild_company_occupancy,
)
from src.application.inventory_reconciliation.kitshop_backlog_ports import (
    KitShopCompanyIdResolver,
    KitShopSalesBacklogStore,
    KitShopSalesGateway,
)
from src.application.inventory_reconciliation.kitshop_sale_receipt_ports import (
    KitShopSaleReceiptStore,
)
from src.application.inventory_reconciliation.kitshop_source_id import (
    build_kitshop_sale_source_id,
)
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.micromarket_loading import (
    ApplyMicromarketSaleToStock,
    extract_machine_code_from_shop_name,
)
from src.application.product_identity import (
    KitShopRecognized,
    KitShopSaleResolve,
    ResolveHold,
    ResolveLegacy,
)
from src.application.product_identity.queries import HOLD_REASON
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale

_LOGGER = logging.getLogger(__name__)

KitShopAlertPhase = Literal["discovery", "drain"]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@runtime_checkable
class KitShopSaleAlertNotifier(Protocol):
    def notify_held(self, *, count: int, reasons: tuple[str, ...]) -> None: ...

    def notify_phase_failed(
        self,
        *,
        phase: KitShopAlertPhase,
        exception_type: str,
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class NoOpKitShopSaleAlertNotifier:
    @beartype
    def notify_held(self, *, count: int, reasons: tuple[str, ...]) -> None:
        del count, reasons

    @beartype
    def notify_phase_failed(
        self,
        *,
        phase: KitShopAlertPhase,
        exception_type: str,
    ) -> None:
        del phase, exception_type


@beartype
@dataclass(frozen=True, slots=True)
class DrainKitShopSalesBacklogResult:
    deducted: int
    held: int
    done: int
    claimed: int
    affected_machine_ids: tuple[MachineId, ...] = ()


def payload_from_detail(detail: object) -> dict[str, object]:
    positions_out: list[dict[str, object]] = []
    for position in detail.positions:  # type: ignore[attr-defined]
        price = position.price
        positions_out.append(
            {
                "PositionId": int(position.position_id),
                "ProductId": int(position.product_id),
                "Quantity": str(position.quantity),
                "Price": None if price is None else str(price),
            },
        )
    occurred = detail.sale_datetime  # type: ignore[attr-defined]
    return {
        "SaleId": int(detail.sale_id),  # type: ignore[attr-defined]
        "CompanyId": int(detail.company_id),  # type: ignore[attr-defined]
        "ShopId": int(detail.shop_id),  # type: ignore[attr-defined]
        "DeviceId": int(detail.device_id),  # type: ignore[attr-defined]
        "SaleDateTime": occurred.isoformat(),
        "Positions": positions_out,
    }


@beartype
@dataclass(frozen=True, slots=True)
class _StoredPosition:
    position_id: int
    product_id: int
    quantity: Decimal
    price: Decimal | None


@beartype
@dataclass(frozen=True, slots=True)
class _StoredDetail:
    sale_id: int
    company_id: int
    shop_id: int
    device_id: int
    sale_datetime: datetime
    positions: tuple[_StoredPosition, ...]


def detail_from_payload(payload: dict[str, object]) -> _StoredDetail:
    raw_positions = payload["Positions"]
    assert isinstance(raw_positions, list)
    positions: list[_StoredPosition] = []
    for item in raw_positions:
        assert isinstance(item, dict)
        price_raw = item["Price"]
        position_id = item["PositionId"]
        product_id = item["ProductId"]
        quantity_raw = item["Quantity"]
        assert isinstance(position_id, int)
        assert isinstance(product_id, int)
        positions.append(
            _StoredPosition(
                position_id=position_id,
                product_id=product_id,
                quantity=Decimal(str(quantity_raw)),
                price=None if price_raw is None else Decimal(str(price_raw)),
            ),
        )
    occurred_raw = payload["SaleDateTime"]
    assert isinstance(occurred_raw, str)
    occurred = datetime.fromisoformat(occurred_raw)
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    sale_id = payload["SaleId"]
    company_id = payload["CompanyId"]
    shop_id = payload["ShopId"]
    device_id = payload["DeviceId"]
    assert isinstance(sale_id, int)
    assert isinstance(company_id, int)
    assert isinstance(shop_id, int)
    assert isinstance(device_id, int)
    return _StoredDetail(
        sale_id=sale_id,
        company_id=company_id,
        shop_id=shop_id,
        device_id=device_id,
        sale_datetime=occurred,
        positions=tuple(positions),
    )


@beartype
@dataclass(slots=True)
class DrainKitShopSalesBacklog:
    gateway: KitShopSalesGateway
    backlog: KitShopSalesBacklogStore
    sales_store: MachineSalesStore
    apply_micromarket_sale: ApplyMicromarketSaleToStock
    company_resolver: KitShopCompanyIdResolver
    receipts: KitShopSaleReceiptStore
    now: Callable[[], datetime] = _utc_now
    unresolved_alert_min: int = 1
    unresolved_alert_notifier: KitShopSaleAlertNotifier = NoOpKitShopSaleAlertNotifier()
    domain_product_identity_enabled: bool = False
    resolve_sale_code: Callable[[str], KitShopSaleResolve] | None = None
    occupancy_store: MachineCompanyOccupancyStore | None = None
    after_occupancy_rebuild: Callable[[], None] | None = None

    @beartype
    def execute(self, *, limit: int = 1) -> DrainKitShopSalesBacklogResult:
        resolver = self.resolve_sale_code
        if self.domain_product_identity_enabled and resolver is None:
            raise ValueError("domain product resolve is required when identity is enabled")
        claimed_ids = self.backlog.claim_pending(limit=limit)
        deducted = 0
        held = 0
        done = 0
        unresolved_batch = 0
        hold_reasons: list[str] = []
        affected_machine_ids: set[MachineId] = set()
        rebuild_ids: set[MachineId] = set()
        ingested_at = self.now()

        for sale_id in claimed_ids:
            stored = self.receipts.load(sale_id)
            if stored is None:
                fetched = self.gateway.get_sale_detail(sale_id)
                payload = payload_from_detail(fetched)
                try:
                    self.receipts.save_if_absent(sale_id=sale_id, payload=payload)
                except Exception:
                    _LOGGER.exception(
                        "kitshop_sale_receipt_save_failed",
                        extra={"sale_id": sale_id},
                    )
                    continue
                _LOGGER.info("kitshop_sale_receipt_saved", extra={"sale_id": sale_id})
                detail = detail_from_payload(payload)
            else:
                detail = detail_from_payload(stored)

            company_id_kit = int(detail.company_id)
            mk_company_id = self.company_resolver.resolve_mk_company_id(
                kit_company_id=company_id_kit,
            )
            if mk_company_id is None:
                _LOGGER.info(
                    "kitshop_sales_drain_hold",
                    extra={"sale_id": sale_id, "reason": "company_miss"},
                )
                self.backlog.mark_hold(sale_id=sale_id, reason="company_miss")
                held += 1
                unresolved_batch += 1
                hold_reasons.append("company_miss")
                continue

            shop_id = int(detail.shop_id)
            shop_name = self.gateway.shop_name(shop_id)
            machine_code = (
                None if shop_name is None else extract_machine_code_from_shop_name(shop_name)
            )
            if machine_code is None:
                reason = "shop_miss" if shop_name is None else "no_machine_code"
                _LOGGER.info(
                    "kitshop_sales_drain_hold",
                    extra={"sale_id": sale_id, "reason": reason},
                )
                self.backlog.mark_hold(sale_id=sale_id, reason=reason)
                held += 1
                unresolved_batch += 1
                hold_reasons.append(reason)
                continue

            occurred_at = _as_utc(detail.sale_datetime)
            positions = detail.positions
            hold_reason: str | None = None
            machine_id = MachineId(machine_code)
            for position in positions:
                qty = Decimal(str(position.quantity))
                if qty < 1:
                    hold_reason = "invalid_quantity"
                    _LOGGER.info(
                        "kitshop_sales_drain_hold",
                        extra={"sale_id": sale_id, "reason": "invalid_quantity"},
                    )
                    continue

                product_id = int(position.product_id)
                vendor = self.gateway.vendor_code(product_id)
                if vendor is None or not str(vendor).strip():
                    if hold_reason != "invalid_quantity":
                        hold_reason = "unresolved_position"
                    _LOGGER.info(
                        "kitshop_sale_unresolved_vendor",
                        extra={
                            "sale_id": sale_id,
                            "product_id": product_id,
                            "position_id": int(position.position_id),
                        },
                    )
                    continue

                vendor_code = str(vendor).strip()
                if self.domain_product_identity_enabled and resolver is not None:
                    resolved = resolver(vendor_code)
                    if isinstance(resolved, ResolveHold):
                        reason = HOLD_REASON[resolved.kind]
                        if hold_reason != "invalid_quantity":
                            hold_reason = reason
                        _LOGGER.info(
                            "kitshop_sales_drain_hold",
                            extra={
                                "sale_id": sale_id,
                                "reason": reason,
                                "code": vendor_code,
                            },
                        )
                        continue
                    if isinstance(resolved, KitShopRecognized):
                        product_code = resolved.number
                        domain_product_id = resolved.domain_product_id
                        if resolved.alias_from:
                            _LOGGER.info(
                                "kitshop_sale_resolved",
                                extra={
                                    "sale_id": sale_id,
                                    "number": resolved.number,
                                    "alias_from": resolved.alias_from,
                                },
                            )
                    elif isinstance(resolved, ResolveLegacy):
                        product_code = resolved.code
                        domain_product_id = ""
                else:
                    product_code = vendor_code
                    domain_product_id = ""

                source_id = build_kitshop_sale_source_id(
                    sale_id=sale_id,
                    position_id=int(position.position_id),
                )
                price = None if position.price is None else Decimal(str(position.price))
                sale = MachineSale(
                    source_id=source_id,
                    machine_id=machine_id,
                    product_code=product_code,
                    quantity=qty,
                    occurred_at=occurred_at,
                    ingested_at=ingested_at,
                    sale_kind="micromarket",
                    kit_matrix_id=None,
                    kit_vending_machine_id=None,
                    kit_line_number=None,
                    machine_code=machine_code,
                    price=price,
                    company_id=mk_company_id,
                    domain_product_id=domain_product_id,
                )
                inserted_now = self.sales_store.insert_if_absent(sale)
                if inserted_now:
                    rebuild_ids.add(machine_id)
                apply_result = self.apply_micromarket_sale.execute(
                    machine_code=machine_code,
                    product_code=sale.product_code,
                    qty=qty,
                    sale_source_id=source_id,
                    occurred_at=occurred_at,
                )
                if apply_result.status == "deducted":
                    deducted += 1
                affected_machine_ids.add(machine_id)

            if hold_reason is not None:
                self.backlog.mark_hold(sale_id=sale_id, reason=hold_reason)
                held += 1
                unresolved_batch += 1
                hold_reasons.append(hold_reason)
            else:
                self.backlog.mark_done(sale_id=sale_id)
                done += 1
                _LOGGER.info(
                    "kitshop_sales_drain_done",
                    extra={"sale_id": sale_id},
                )

        if unresolved_batch >= self.unresolved_alert_min and hold_reasons:
            self.unresolved_alert_notifier.notify_held(
                count=unresolved_batch,
                reasons=tuple(sorted(set(hold_reasons))),
            )

        if self.occupancy_store is not None:
            for machine_id in sorted(rebuild_ids, key=lambda item: item.value):
                sales = self.sales_store.list_with_company_id(machine_id)
                intervals = rebuild_company_occupancy(machine_id, sales)
                self.occupancy_store.replace_for_machine(machine_id, intervals)
                _LOGGER.info(
                    "machine_company_occupancy rebuilt machine_id=%s interval_count=%s",
                    machine_id.value,
                    len(intervals),
                )
            if rebuild_ids and self.after_occupancy_rebuild is not None:
                try:
                    self.after_occupancy_rebuild()
                except Exception:
                    _LOGGER.exception("kitshop_export_after_occupancy_failed")

        return DrainKitShopSalesBacklogResult(
            deducted=deducted,
            held=held,
            done=done,
            claimed=len(claimed_ids),
            affected_machine_ids=tuple(
                sorted(affected_machine_ids, key=lambda item: item.value),
            ),
        )


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
