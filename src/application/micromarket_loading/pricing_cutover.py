from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from beartype import beartype

from src.application.micromarket_loading.ports import (
    MicromarketPlanogramStore,
    MicromarketPriceChangeJournal,
)
from src.application.micromarket_loading.pricing_stores import (
    MicromarketPriceChangeJournalEntry,
)


@beartype
@dataclass(frozen=True, slots=True)
class CutoverMicromarketPlanogramPrices:
    store: MicromarketPlanogramStore
    journal: MicromarketPriceChangeJournal
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)
    actor: str = "system"

    @beartype
    def execute(self) -> int:
        painted = 0
        now = self.now_factory()
        for doc in self.store.list_all():
            new_lines = tuple(replace(line, price_origin="manual") for line in doc.lines)
            self.store.upsert(replace(doc, lines=new_lines, updated_at=now))
            for line in new_lines:
                self.journal.append(
                    MicromarketPriceChangeJournalEntry(
                        machine_id=doc.machine_code,
                        product_code=line.product_code or (line.domain_product_id or ""),
                        old_price_rub=line.price_rub,
                        new_price_rub=line.price_rub,
                        origin="cutover",
                        actor=self.actor,
                        reason=None,
                        at=now,
                    )
                )
                painted += 1
        return painted
