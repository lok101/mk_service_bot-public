from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

import httpx
import pytest
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.master_data.companies import KitPlatformRole
from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.api_models.matrix import GoodsMatrixModel
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.catalog_merge import (
    fetch_merged_catalog,
    merge_matrices,
    merge_recipes,
)
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.rate_limiting import SyncRateLimiter


@dataclass(slots=True)
class StubRequestIdStore:
    next_value: int

    def next_id(self, *, login: str) -> int:
        return self.next_value

    def bump_floor(self, *, login: str, floor: int) -> None:
        self.next_value = max(self.next_value, floor)


def _matrix(matrix_id: int) -> GoodsMatrixModel:
    return GoodsMatrixModel.model_validate(
        {
            "MatrixId": matrix_id,
            "MatrixName": f"M{matrix_id}",
            "MatrixType": 1,
            "Details": [],
        }
    )


def test_merge_matrices_overwrites_on_collision_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    target: dict[int, GoodsMatrixModel] = {_matrix(1).id: _matrix(1)}
    colliding = GoodsMatrixModel.model_validate(
        {
            "MatrixId": 1,
            "MatrixName": "M99",
            "MatrixType": 1,
            "Details": [],
        }
    )
    merge_matrices(target, [colliding], account_label="child")
    assert target[1].name == "M99"
    assert any("Коллизия MatrixId=1" in record.message for record in caplog.records)


def test_merge_recipes_overwrites_on_collision_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    recipe = RecipeModel.model_validate({"FormulationId": 1, "FormulationName": "2301 | Latte"})
    colliding = RecipeModel.model_validate({"FormulationId": 1, "FormulationName": "9999 | Other"})
    target: dict[int, RecipeModel] = {recipe.id: recipe}
    merge_recipes(target, [colliding], account_label="child")
    assert target[1].name == "9999 | Other"
    assert any("Коллизия FormulationId=1" in record.message for record in caplog.records)


def test_fetch_merged_catalog_fetches_accounts_in_parallel() -> None:
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        path = request.url.path
        if path.endswith("/GetGoodsMatrices"):
            return httpx.Response(200, json={"ResultCode": 0, "GoodsMatrices": []})
        return httpx.Response(200, json={"ResultCode": 0, "Formulations": []})

    settings = KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = SyncRateLimiter(max_requests=100, time_window=1.0)
    head_client = KitVendingApiClient(
        account=make_platform_account(
            account_key="head",
            company_id=1,
            kit_company_id=1,
            login="head",
            password="p",
            role=KitPlatformRole.SALES_POLL,
        ),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=1),
        rate_limiter=limiter,
    )
    child_client = KitVendingApiClient(
        account=make_platform_account(
            account_key="child",
            company_id=2,
            kit_company_id=2,
            login="child",
            password="p",
            role=KitPlatformRole.CATALOG,
        ),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=2),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )

    fetch_merged_catalog([head_client, child_client])

    assert max_in_flight >= 2


def test_fetch_merged_catalog_calls_each_client_sequentially_inside_account() -> None:
    head_matrix = _matrix(10)
    child_matrix = _matrix(20)
    head_recipe = RecipeModel.model_validate(
        {"FormulationId": 1, "FormulationName": "2301 | Latte"}
    )
    child_recipe = RecipeModel.model_validate(
        {"FormulationId": 2, "FormulationName": "2101 | Snack"}
    )
    head_matrix_calls = 0
    head_recipe_calls = 0
    child_matrix_calls = 0
    child_recipe_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal head_matrix_calls, head_recipe_calls, child_matrix_calls, child_recipe_calls
        body = json.loads(request.content)
        login = body["Auth"]["UserLogin"]
        path = request.url.path
        if path.endswith("/GetGoodsMatrices"):
            if login == "head":
                head_matrix_calls += 1
                return httpx.Response(
                    200,
                    json={
                        "ResultCode": 0,
                        "GoodsMatrices": [
                            {
                                "MatrixId": head_matrix.id,
                                "MatrixName": head_matrix.name,
                                "MatrixType": 1,
                                "Details": [],
                            }
                        ],
                    },
                )
            child_matrix_calls += 1
            return httpx.Response(
                200,
                json={
                    "ResultCode": 0,
                    "GoodsMatrices": [
                        {
                            "MatrixId": child_matrix.id,
                            "MatrixName": child_matrix.name,
                            "MatrixType": 1,
                            "Details": [],
                        }
                    ],
                },
            )
        if login == "head":
            head_recipe_calls += 1
            return httpx.Response(
                200,
                json={
                    "ResultCode": 0,
                    "Formulations": [
                        {
                            "FormulationId": head_recipe.id,
                            "FormulationName": head_recipe.name,
                        }
                    ],
                },
            )
        child_recipe_calls += 1
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "Formulations": [
                    {
                        "FormulationId": child_recipe.id,
                        "FormulationName": child_recipe.name,
                    }
                ],
            },
        )

    settings = KitVendingSettings.model_construct(
        api_base_url="https://kit.example/APIService.svc",
        backoff_seconds=0.01,
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    limiter = SyncRateLimiter(max_requests=100, time_window=1.0)
    head_client = KitVendingApiClient(
        account=make_platform_account(
            account_key="head",
            company_id=1,
            kit_company_id=1,
            login="head",
            password="p",
            role=KitPlatformRole.SALES_POLL,
        ),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=1),
        rate_limiter=limiter,
    )
    child_client = KitVendingApiClient(
        account=make_platform_account(
            account_key="child",
            company_id=2,
            kit_company_id=2,
            login="child",
            password="p",
            role=KitPlatformRole.CATALOG,
        ),
        settings=settings,
        http_client=http,
        request_id_store=StubRequestIdStore(next_value=2),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )

    result = fetch_merged_catalog([head_client, child_client])

    assert result["matrices"] == {10: head_matrix, 20: child_matrix}
    assert result["recipes"] == {1: head_recipe, 2: child_recipe}
    assert head_matrix_calls == 1
    assert head_recipe_calls == 1
    assert child_matrix_calls == 1
    assert child_recipe_calls == 1
