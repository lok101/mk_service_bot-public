from __future__ import annotations

from dataclasses import dataclass, field

from beartype import beartype

from src.application.master_data.companies import MasterCompany, validate_bindings_unique


@beartype
@dataclass(slots=True)
class InMemoryCompanyStore:
    _by_id: dict[int, MasterCompany] = field(default_factory=dict)

    def get(self, company_id: int) -> MasterCompany | None:
        return self._by_id.get(company_id)

    def upsert(self, company: MasterCompany) -> None:
        self._by_id[company.company_id] = company
        validate_bindings_unique(self.list_all())

    def list_all(self) -> tuple[MasterCompany, ...]:
        return tuple(self._by_id.values())

    def is_empty(self) -> bool:
        return not self._by_id
