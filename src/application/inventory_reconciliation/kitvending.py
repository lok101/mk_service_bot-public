from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, Literal

from beartype import beartype

from src.domain.machine_sales import SaleKind

HOLDING_SKIP_ALERT_SAMPLE_SIZE: Final = 5

ReasonClass = Literal[
    "critical_product_resolve",
    "no_machine_code",
    "company_unresolved",
    "line_neg_1",
    "product_zero",
]


@beartype
@dataclass(frozen=True, slots=True)
class KitVendingSaleRow:
    source_id: str
    vending_machine_code: str
    product_code: str
    quantity: Decimal
    occurred_at: datetime
    sale_kind: SaleKind = "unknown"
    kit_matrix_id: int | None = None
    kit_vending_machine_id: int | None = None
    kit_line_number: int | None = None
    price: Decimal | None = None
    company_id: int | None = None
    domain_product_id: str = ""


@beartype
@dataclass(frozen=True, slots=True)
class HoldingSkipSample:
    occurred_at: datetime
    reason_class: ReasonClass
    machine_key: str
    vending_machine_name: str | None = None
    matrix_id: int | None = None
    kit_vending_machine_id: int | None = None
    detail: str = ""


@beartype
@dataclass(frozen=True, slots=True)
class KitVendingFetchStats:
    skipped_unresolved_product: int = 0  # total product skips (holding + non-holding)
    skipped_unresolved_product_non_holding: int = 0
    skipped_no_machine_code: int = 0  # always holding
    holding_skip_count: int = 0
    hold_at: datetime | None = None
    holding_samples: tuple[HoldingSkipSample, ...] = ()
    fingerprint_pairs: tuple[tuple[str, ReasonClass], ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class RawKitSaleIdentity:
    source_id: str
    kit_vending_machine_id: int
    vending_machine_name: str | None
    vending_machine_code: str | None
    occurred_at: datetime
    line_number: int
    matrix_id: int | None
    goods_name: str | None


@beartype
@dataclass(frozen=True, slots=True)
class KitSaleResolveSkip:
    reason_class: ReasonClass
    holding: bool


@beartype
@dataclass(frozen=True, slots=True)
class KitSaleResolveSuccess:
    row: KitVendingSaleRow


@beartype
@dataclass(frozen=True, slots=True)
class KitSalePriceRow:
    """Сырой Kit-ряд для price backfill: source_id + непарсенный Sum.

    `source_id`/`sum_value` типизированы как `| None` для fake-адаптеров в тестах
    (реальный `main_api.get_sales` + `SaleModel` их всегда заполняет).
    """

    source_id: str | None
    sum_value: float | None
