from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class DraftLine:
    product_code: str
    target_qty: int
    stock_qty: Decimal
    need_qty: Decimal
    launch_qty: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class DraftSaved:
    lines: tuple[DraftLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class OrderLaunchIntended:
    order_id: str


@beartype
@dataclass(frozen=True, slots=True)
class OrderOpened:
    order_id: str
    move_id: str
    lines: tuple[DraftLine, ...]
    opened_at: datetime
    opened_operational_day: date


@beartype
@dataclass(frozen=True, slots=True)
class OrderRecounted:
    deltas: tuple[tuple[str, Decimal], ...]
    at: datetime
    shelf_before: tuple[tuple[str, Decimal], ...] | None = None


@beartype
@dataclass(frozen=True, slots=True)
class OrderRecountReplaced:
    deltas: tuple[tuple[str, Decimal], ...]
    at: datetime


OPS_CONFIRMED_WITHOUT_RECOUNT = "ops_confirmed_without_recount"


@beartype
@dataclass(frozen=True, slots=True)
class OrderClosed:
    at: datetime
    close_kind: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class OrderRolledBack:
    at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class OrderAlertRecorded:
    order_id: str
    operational_day: date


@beartype
@dataclass(frozen=True, slots=True)
class OrderVisitLinked:
    visit_id: str


@beartype
@dataclass(frozen=True, slots=True)
class OrderMoveRepaired:
    """Ops recovery: OPEN cycle points at a recreated MoySklad move id."""

    move_id: str


MicromarketLoadingCycleEvent = (
    DraftSaved
    | OrderLaunchIntended
    | OrderOpened
    | OrderRecounted
    | OrderRecountReplaced
    | OrderClosed
    | OrderRolledBack
    | OrderAlertRecorded
    | OrderVisitLinked
    | OrderMoveRepaired
)
