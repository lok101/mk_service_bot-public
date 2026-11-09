from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class SettlementAnalysisPrefs:
    unit_prices: dict[str, Decimal]
    recoverable_product_codes: frozenset[str]
    allowed_loss_pct: Decimal

    @classmethod
    def empty(cls) -> SettlementAnalysisPrefs:
        return cls(
            unit_prices={},
            recoverable_product_codes=frozenset(),
            allowed_loss_pct=Decimal("0"),
        )


@runtime_checkable
class SettlementAnalysisPrefsStore(Protocol):
    @beartype
    def get(self, telegram_user_id: int) -> SettlementAnalysisPrefs: ...

    @beartype
    def save(self, telegram_user_id: int, prefs: SettlementAnalysisPrefs) -> None: ...
