from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class MainWarehouseStockSnapshot:
    warehouse_id: UUID
    refreshed_at: datetime
    qty_by_catalog_code: Mapping[str, Decimal]
