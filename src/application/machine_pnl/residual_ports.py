from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import TechnicianId


@beartype
@dataclass(frozen=True, slots=True)
class ResidualSessionView:
    session_id: str
    technician_id: str
    anchor_at: datetime
    period_ids: tuple[str, ...]
    residual_by_sku: Mapping[str, Decimal]


@runtime_checkable
class ResidualSessionReader(Protocol):
    @beartype
    def find_completed_containing(
        self,
        period_id: str,
        *,
        technician_id: TechnicianId,
    ) -> tuple[ResidualSessionView, ...]: ...
