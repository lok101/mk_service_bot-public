from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypedDict

from beartype import beartype

from src.infrastructure.integrations.kitvending.api_models.matrix import MatrixModel
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel


class CatalogFetchResult(TypedDict):
    matrices: dict[int, MatrixModel]
    recipes: dict[int, RecipeModel]


@beartype
@dataclass
class CatalogCache:
    ttl_seconds: int | float
    now: Callable[[], float]
    _loaded_at: float | None = field(default=None, init=False)
    _matrices_by_id: dict[int, MatrixModel] = field(default_factory=dict, init=False)
    _recipes_by_id: dict[int, RecipeModel] = field(default_factory=dict, init=False)

    def get_or_load(
        self,
        fetch: Callable[[], CatalogFetchResult],
        *,
        now: float | None = None,
    ) -> tuple[dict[int, MatrixModel], dict[int, RecipeModel]]:
        timestamp = self.now() if now is None else now
        if self._loaded_at is not None and timestamp - self._loaded_at < self.ttl_seconds:
            return self._matrices_by_id, self._recipes_by_id

        data = fetch()
        self._matrices_by_id = dict(data["matrices"])
        self._recipes_by_id = dict(data["recipes"])
        self._loaded_at = timestamp
        return self._matrices_by_id, self._recipes_by_id

    @beartype
    def load(
        self,
        fetch: Callable[[], CatalogFetchResult],
    ) -> tuple[dict[int, MatrixModel], dict[int, RecipeModel]]:
        return self.get_or_load(fetch, now=self.now())
