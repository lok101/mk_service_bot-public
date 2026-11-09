from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class KitShopSalesBacklogStore(Protocol):
    def upsert_pending(self, *, sale_id: int) -> bool: ...  # True if newly inserted

    def claim_pending(self, *, limit: int = 1) -> list[int]: ...

    def mark_done(self, *, sale_id: int) -> None: ...

    def mark_hold(self, *, sale_id: int, reason: str) -> None: ...

    def get_status(self, sale_id: int) -> str | None: ...


@runtime_checkable
class KitShopSalesIngestCursorStore(Protocol):
    def load(self) -> datetime | None: ...

    def save(self, watermark: datetime) -> None: ...


@runtime_checkable
class KitShopSalesGateway(Protocol):
    def list_sales_since(self, *, since: datetime, until: datetime) -> list[object]: ...

    def get_sale_detail(self, sale_id: int) -> object: ...

    def shop_name(self, shop_id: int) -> str | None: ...

    def vendor_code(self, product_id: int) -> str | None: ...


@runtime_checkable
class KitShopCompanyIdResolver(Protocol):
    """kit Shop CompanyId → MK company_id. Не импортировать master_data в IR."""

    def resolve_mk_company_id(self, *, kit_company_id: int) -> int | None: ...
