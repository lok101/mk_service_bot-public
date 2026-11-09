from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

StockSource = Literal["actual_prev", "actual"]


@beartype
@dataclass(frozen=True, slots=True)
class DuplicateProductCodeInStock:
    product_code: str
    source: StockSource


@beartype
@dataclass(frozen=True, slots=True)
class NaiveDatetimeNotAllowed:
    field: str
