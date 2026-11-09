from __future__ import annotations

from src.infrastructure.integrations.kitvending.api_models.matrix import GoodsMatrixModel
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.catalog_cache import CatalogCache


def test_catalog_cache_reuses_matrices_within_ttl() -> None:
    calls = 0

    def fetch() -> dict[str, dict[int, object]]:
        nonlocal calls
        calls += 1
        return {"matrices": {}, "recipes": {}}

    cache = CatalogCache(ttl_seconds=3600, now=lambda: 1000.0)
    cache.get_or_load(fetch, now=1000.0)
    cache.get_or_load(fetch, now=1500.0)
    assert calls == 1


def test_catalog_cache_returns_matrices_and_recipes_by_id() -> None:
    matrix = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 10,
            "MatrixName": "Snack",
            "MatrixType": 1,
            "Details": [
                {
                    "LineNumber": 1,
                    "Price2": 10.0,
                    "GoodsName": "2101 | Snack",
                    "MaxCount": 5,
                }
            ],
        }
    )
    recipe = RecipeModel.model_validate(
        {"FormulationId": 20, "FormulationName": "2301 | Latte"},
    )

    def fetch() -> dict[str, dict[int, object]]:
        return {"matrices": {matrix.id: matrix}, "recipes": {recipe.id: recipe}}

    cache = CatalogCache(ttl_seconds=3600, now=lambda: 1000.0)
    matrices_by_id, recipes_by_id = cache.get_or_load(fetch, now=1000.0)
    assert matrices_by_id == {10: matrix}
    assert recipes_by_id == {20: recipe}


def test_catalog_cache_refetches_after_ttl_expired() -> None:
    calls = 0

    def fetch() -> dict[str, dict[int, object]]:
        nonlocal calls
        calls += 1
        return {"matrices": {}, "recipes": {}}

    cache = CatalogCache(ttl_seconds=100, now=lambda: 1000.0)
    cache.get_or_load(fetch, now=1000.0)
    cache.get_or_load(fetch, now=1101.0)
    assert calls == 2


def test_catalog_cache_load_uses_callable_fetch_once() -> None:
    calls = 0

    def fetch() -> dict[str, dict[int, object]]:
        nonlocal calls
        calls += 1
        return {"matrices": {}, "recipes": {}}

    cache = CatalogCache(ttl_seconds=3600, now=lambda: 1000.0)
    cache.load(fetch)
    cache.load(fetch)
    assert calls == 1
