from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.domain.micromarket_pricing.formula import MicromarketPricingRules

PriceChangeOrigin = Literal["calculated", "manual", "reset", "cutover"]


@beartype
@dataclass(slots=True)
class EmptyProcurementMirrorStore:
    """No-op mirrors for hosts without procurement wiring (recalc skips purchase)."""

    def get(self, catalog_code: str) -> ProcurementMirror | None:
        del catalog_code
        return None

    def upsert(self, mirror: ProcurementMirror) -> None:
        del mirror

    def delete(self, catalog_code: str) -> None:
        del catalog_code

    def codes(self) -> tuple[str, ...]:
        return ()


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPriceChangeJournalEntry:
    machine_id: str
    product_code: str
    old_price_rub: Decimal | None
    new_price_rub: Decimal
    origin: PriceChangeOrigin
    actor: str
    reason: str | None
    at: datetime


@beartype
@dataclass(slots=True)
class InMemoryMicromarketPricingRulesStore:
    _rules: MicromarketPricingRules | None = None

    def get(self) -> MicromarketPricingRules | None:
        return self._rules

    def save(self, rules: MicromarketPricingRules) -> None:
        self._rules = rules


@beartype
@dataclass(slots=True)
class InMemoryMicromarketProductMultiplierStore:
    _by_code: dict[str, Decimal] = field(default_factory=dict)

    def get(self, product_code: str) -> Decimal | None:
        return self._by_code.get(product_code)

    def list_all(self) -> dict[str, Decimal]:
        return dict(self._by_code)

    def upsert(self, product_code: str, multiplier: Decimal) -> None:
        self._by_code[product_code] = multiplier

    def delete(self, product_code: str) -> None:
        self._by_code.pop(product_code, None)


@beartype
@dataclass(slots=True)
class InMemoryMicromarketMachineMultiplierStore:
    _by_machine: dict[str, Decimal] = field(default_factory=dict)

    def get(self, machine_id: str) -> Decimal | None:
        return self._by_machine.get(machine_id)

    def list_all(self) -> dict[str, Decimal]:
        return dict(self._by_machine)

    def upsert(self, machine_id: str, multiplier: Decimal) -> None:
        self._by_machine[machine_id] = multiplier


@beartype
@dataclass(slots=True)
class InMemoryMicromarketPriceChangeJournal:
    _entries: list[MicromarketPriceChangeJournalEntry] = field(default_factory=list)

    def append(self, entry: MicromarketPriceChangeJournalEntry) -> None:
        self._entries.append(entry)

    def list_for_machine(
        self,
        machine_id: str,
        *,
        limit: int = 100,
    ) -> tuple[MicromarketPriceChangeJournalEntry, ...]:
        matched = [e for e in self._entries if e.machine_id == machine_id]
        return tuple(matched[-limit:])
