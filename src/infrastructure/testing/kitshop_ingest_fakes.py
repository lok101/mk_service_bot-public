from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from beartype import beartype

from src.application.inventory_reconciliation.kitshop_backlog_ports import (
    KitShopCompanyIdResolver,
    KitShopSalesBacklogStore,
    KitShopSalesGateway,
    KitShopSalesIngestCursorStore,
)
from src.application.inventory_reconciliation.kitshop_sale_receipt_ports import (
    KitShopSaleReceiptStore,
)


@beartype
@dataclass(slots=True)
class InMemoryKitShopSalesBacklogStore(KitShopSalesBacklogStore):
    _status: dict[int, str] = field(default_factory=dict)
    _hold_reason: dict[int, str] = field(default_factory=dict)
    _order: list[int] = field(default_factory=list)

    @beartype
    def upsert_pending(self, *, sale_id: int) -> bool:
        if sale_id in self._status:
            return False
        self._status[sale_id] = "pending"
        self._order.append(sale_id)
        return True

    @beartype
    def claim_pending(self, *, limit: int = 1) -> list[int]:
        pending = [sale_id for sale_id in self._order if self._status.get(sale_id) == "pending"]
        hold = [sale_id for sale_id in self._order if self._status.get(sale_id) == "hold"]
        return (pending + hold)[:limit]

    @beartype
    def mark_done(self, *, sale_id: int) -> None:
        self._status[sale_id] = "done"
        self._hold_reason.pop(sale_id, None)

    @beartype
    def mark_hold(self, *, sale_id: int, reason: str) -> None:
        self._status[sale_id] = "hold"
        self._hold_reason[sale_id] = reason

    @beartype
    def get_status(self, sale_id: int) -> str | None:
        return self._status.get(sale_id)


@beartype
@dataclass(slots=True)
class InMemoryKitShopSalesIngestCursorStore(KitShopSalesIngestCursorStore):
    _watermark: datetime | None = None

    @beartype
    def load(self) -> datetime | None:
        return self._watermark

    @beartype
    def save(self, watermark: datetime) -> None:
        self._watermark = watermark


@beartype
@dataclass(frozen=True, slots=True)
class FakeKitShopSaleListItem:
    sale_id: int
    sale_datetime: datetime


@beartype
@dataclass(frozen=True, slots=True)
class FakeKitShopSalePosition:
    position_id: int
    product_id: int
    quantity: Decimal
    price: Decimal | None = None


@beartype
@dataclass(frozen=True, slots=True)
class FakeKitShopSaleDetail:
    sale_id: int
    company_id: int
    shop_id: int
    device_id: int
    sale_datetime: datetime
    positions: tuple[FakeKitShopSalePosition, ...]


@beartype
@dataclass(slots=True)
class FakeKitShopSalesGateway(KitShopSalesGateway):
    list_sales: list[dict[str, object]] = field(default_factory=list)
    _details: dict[int, FakeKitShopSaleDetail] = field(default_factory=dict)
    _shop_names: dict[int, str] = field(default_factory=dict)
    _vendor_codes: dict[int, str] = field(default_factory=dict)
    detail_fetches: int = 0

    @classmethod
    @beartype
    def single_position(
        cls,
        *,
        sale_id: int,
        shop_name: str,
        vendor_code: str,
        device_id: int,
        qty: Decimal,
        kit_company_id: int,
        shop_id: int = 10,
        product_id: int = 20,
        position_id: int = 1,
        sale_datetime: datetime | None = None,
        price: Decimal | None = None,
    ) -> FakeKitShopSalesGateway:
        occurred = sale_datetime or datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        detail = FakeKitShopSaleDetail(
            sale_id=sale_id,
            company_id=kit_company_id,
            shop_id=shop_id,
            device_id=device_id,
            sale_datetime=occurred,
            positions=(
                FakeKitShopSalePosition(
                    position_id=position_id,
                    product_id=product_id,
                    quantity=qty,
                    price=price,
                ),
            ),
        )
        return cls(
            list_sales=[{"sale_id": sale_id, "sale_datetime": occurred}],
            _details={sale_id: detail},
            _shop_names={shop_id: shop_name},
            _vendor_codes={product_id: vendor_code},
        )

    @classmethod
    @beartype
    def two_positions(
        cls,
        *,
        sale_id: int,
        shop_name: str,
        kit_company_id: int = 1,
        shop_id: int = 10,
        device_id: int = 999,
        sale_datetime: datetime | None = None,
    ) -> FakeKitShopSalesGateway:
        occurred = sale_datetime or datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        detail = FakeKitShopSaleDetail(
            sale_id=sale_id,
            company_id=kit_company_id,
            shop_id=shop_id,
            device_id=device_id,
            sale_datetime=occurred,
            positions=(
                FakeKitShopSalePosition(
                    position_id=1,
                    product_id=20,
                    quantity=Decimal("1"),
                ),
                FakeKitShopSalePosition(
                    position_id=2,
                    product_id=21,
                    quantity=Decimal("1"),
                ),
            ),
        )
        return cls(
            list_sales=[{"sale_id": sale_id, "sale_datetime": occurred}],
            _details={sale_id: detail},
            _shop_names={shop_id: shop_name},
            _vendor_codes={20: "2311", 21: "2312"},
        )

    @beartype
    def list_sales_since(self, *, since: datetime, until: datetime) -> list[object]:
        items: list[object] = []
        for raw in self.list_sales:
            sale_id_value = raw["sale_id"]
            if not isinstance(sale_id_value, int):
                raise TypeError(f"sale_id must be int, got {type(sale_id_value)!r}")
            sale_id = sale_id_value
            sale_datetime = raw["sale_datetime"]
            assert isinstance(sale_datetime, datetime)
            if since <= sale_datetime <= until:
                items.append(FakeKitShopSaleListItem(sale_id=sale_id, sale_datetime=sale_datetime))
        return items

    @beartype
    def get_sale_detail(self, sale_id: int) -> object:
        self.detail_fetches += 1
        return self._details[sale_id]

    @beartype
    def shop_name(self, shop_id: int) -> str | None:
        return self._shop_names.get(shop_id)

    @beartype
    def vendor_code(self, product_id: int) -> str | None:
        return self._vendor_codes.get(product_id)


@beartype
@dataclass(frozen=True, slots=True)
class FakeKitShopCompanyResolver(KitShopCompanyIdResolver):
    _map: dict[int, int] = field(default_factory=dict)

    @beartype
    def resolve_mk_company_id(self, *, kit_company_id: int) -> int | None:
        return self._map.get(kit_company_id)


@beartype
@dataclass(slots=True)
class InMemoryKitShopSaleReceiptStore(KitShopSaleReceiptStore):
    _payloads: dict[int, dict[str, object]] = field(default_factory=dict)

    @beartype
    def load(self, sale_id: int) -> dict[str, object] | None:
        found = self._payloads.get(sale_id)
        if found is None:
            return None
        return dict(found)

    @beartype
    def save_if_absent(self, *, sale_id: int, payload: dict[str, object]) -> None:
        if sale_id in self._payloads:
            return
        self._payloads[sale_id] = dict(payload)
