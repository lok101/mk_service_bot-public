from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

SaleSkipReasonClass = Literal[
    "critical_product_resolve",
    "no_machine_code",
    "company_unresolved",
    "line_neg_1",
    "product_zero",
]


@beartype
@dataclass(frozen=True)
class MachineSaleSkip:
    source_id: str
    reason_class: SaleSkipReasonClass
    kit_vending_machine_id: int
    vending_machine_name: str | None
    occurred_at: datetime
    line_number: int
    matrix_id: int | None
    goods_name: str | None
    external_id: str | None
    first_seen_at: datetime
    last_seen_at: datetime
