from __future__ import annotations

from dataclasses import dataclass, field, replace

from beartype import beartype

from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore


@beartype
@dataclass(slots=True)
class InMemoryMachineSaleSkipStore(MachineSaleSkipStore):
    _by_source_id: dict[str, MachineSaleSkip] = field(default_factory=dict)

    @beartype
    def upsert(self, skip: MachineSaleSkip) -> None:
        existing = self._by_source_id.get(skip.source_id)
        if existing is None:
            self._by_source_id[skip.source_id] = skip
            return
        self._by_source_id[skip.source_id] = replace(
            skip,
            first_seen_at=existing.first_seen_at,
            last_seen_at=skip.last_seen_at,
        )

    @beartype
    def get(self, source_id: str) -> MachineSaleSkip | None:
        return self._by_source_id.get(source_id)

    @beartype
    def delete_by_source_id(self, source_id: str) -> bool:
        if source_id not in self._by_source_id:
            return False
        del self._by_source_id[source_id]
        return True
