from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.shared.admin_nav import AdminNavStructure


@beartype
@dataclass(slots=True)
class InMemoryAdminNavStructureStore:
    _structure: AdminNavStructure | None = None

    def get(self) -> AdminNavStructure | None:
        return self._structure

    def save(self, structure: AdminNavStructure) -> None:
        self._structure = structure
