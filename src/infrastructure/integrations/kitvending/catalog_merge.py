from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from beartype import beartype

from src.infrastructure.integrations.kitvending.api_models.matrix import MatrixModel
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.catalog_cache import CatalogFetchResult
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient

_LOGGER = logging.getLogger(__name__)


@beartype
def merge_matrices(
    target: dict[int, MatrixModel],
    matrices: Sequence[MatrixModel],
    *,
    account_label: str,
) -> None:
    for matrix in matrices:
        if matrix.id in target:
            _LOGGER.warning(
                "Коллизия MatrixId=%s при слиянии каталога (аккаунт %s) — перезапись.",
                matrix.id,
                account_label,
            )
        target[matrix.id] = matrix


@beartype
def merge_recipes(
    target: dict[int, RecipeModel],
    recipes: Sequence[RecipeModel],
    *,
    account_label: str,
) -> None:
    for recipe in recipes:
        if recipe.id in target:
            _LOGGER.warning(
                "Коллизия FormulationId=%s при слиянии каталога (аккаунт %s) — перезапись.",
                recipe.id,
                account_label,
            )
        target[recipe.id] = recipe


@beartype
def _fetch_catalog_for_client(
    client: KitVendingApiClient,
) -> tuple[str, list[MatrixModel], list[RecipeModel]]:
    collection = client.get_goods_matrices()
    recipes = client.get_formulations()
    return client.account.label, collection.get_all_matrices(), recipes


@beartype
def fetch_merged_catalog(clients: Sequence[KitVendingApiClient]) -> CatalogFetchResult:
    matrices_by_id: dict[int, MatrixModel] = {}
    recipes_by_id: dict[int, RecipeModel] = {}
    if not clients:
        return {"matrices": matrices_by_id, "recipes": recipes_by_id}

    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        futures = [executor.submit(_fetch_catalog_for_client, client) for client in clients]
        for future in as_completed(futures):
            label, matrices, recipes = future.result()
            merge_matrices(matrices_by_id, matrices, account_label=label)
            merge_recipes(recipes_by_id, recipes, account_label=label)
    return {"matrices": matrices_by_id, "recipes": recipes_by_id}
