from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.inventory_reconciliation import (
    KitVendingFetchStats,
    KitVendingSaleRow,
)
from src.domain.machine_sales import SaleKind
from src.infrastructure.integrations.kitvending.api_models.enums import VendingMachineKind
from src.infrastructure.integrations.kitvending.parsing.utils import compute_vending_machine_type

__all__ = ["StubKitVendingClient"]


@beartype
def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


@beartype
def _sale_kind_from_row(row: dict[str, str]) -> SaleKind:
    if "sale_kind" in row:
        return row["sale_kind"]  # type: ignore[return-value]
    kind = compute_vending_machine_type(row["vending_machine_code"])
    if kind == VendingMachineKind.SNACK:
        return "snack"
    if kind == VendingMachineKind.COFFEE:
        return "coffee"
    return "unknown"


@beartype
@dataclass(slots=True)
class StubKitVendingClient:
    rows: list[dict[str, str]]
    fetch_stats: KitVendingFetchStats = field(default_factory=KitVendingFetchStats)
    last_fetch_stats: KitVendingFetchStats = field(default_factory=KitVendingFetchStats)

    @beartype
    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]:
        self.last_fetch_stats = self.fetch_stats
        parsed: list[KitVendingSaleRow] = []
        for row in self.rows:
            occurred_at = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00"))
            if occurred_at <= since:
                continue
            if until is not None and occurred_at > until:
                continue
            parsed.append(
                KitVendingSaleRow(
                    source_id=row["source_id"],
                    vending_machine_code=row["vending_machine_code"],
                    product_code=row["product_code"],
                    quantity=Decimal(row["quantity"]),
                    occurred_at=occurred_at,
                    sale_kind=_sale_kind_from_row(row),
                    kit_matrix_id=_optional_int(row.get("kit_matrix_id")),
                    kit_vending_machine_id=_optional_int(row.get("kit_vending_machine_id")),
                    kit_line_number=_optional_int(row.get("kit_line_number")),
                    price=Decimal(row["price"]) if "price" in row else None,
                    company_id=_optional_int(row.get("company_id")),
                ),
            )
        return parsed
