from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.domain.matrix_pricing.formula import BaseMarginParams


@beartype
@dataclass(slots=True)
class InMemoryMatrixBaseMarginStore:
    _params: BaseMarginParams | None = None

    def get(self) -> BaseMarginParams | None:
        return self._params

    def save(self, params: BaseMarginParams) -> None:
        self._params = params
