from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.config.kitvending import KitVendingSettings
from src.infrastructure.kitvending.deploy.client import KitVendingDeployClient
from src.infrastructure.kitvending.deploy.models import (
    KitMatrixCommandCode,
    KitMatrixPosition,
    KitVendingMachineRecord,
)
from src.infrastructure.rate_limiting import SyncRateLimiter


@dataclass(slots=True)
class StubRequestIdStore:
    next_value: int

    def next_id(self, *, login: str) -> int:
        return self.next_value

    def bump_floor(self, *, login: str, floor: int) -> None:
        self.next_value = max(self.next_value, floor)


def _client(handler) -> KitVendingDeployClient:
    return KitVendingDeployClient(
        account=make_platform_account(
            company_id=42, kit_company_id=42, login="user", password="pass"
        ),
        settings=KitVendingSettings.model_construct(
            api_base_url="https://kit.example/APIService.svc",
            backoff_seconds=0.01,
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_id_store=StubRequestIdStore(next_value=123),
        rate_limiter=SyncRateLimiter(max_requests=100, time_window=1.0),
    )


def test_create_pieces_matrix_sends_positions_and_returns_matrix_id() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ResultCode": 0, "Id": 77})

    matrix_id = _client(handler).create_pieces_matrix(
        "snacks_main_512_2026-07-09",
        (KitMatrixPosition(1, "Кола", "120", "120", 10),),
    )
    assert matrix_id == 77
    assert captured["path"].endswith("/CreatePiecesMatrix")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["MatrixName"] == "snacks_main_512_2026-07-09"
    assert body["Positions"][0]["Price2"] == "120"


def test_apply_matrix_sends_matrix_and_vm_ids() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ResultCode": 0})

    _client(handler).apply_matrix(matrix_id=77, vending_machine_id=1001)
    assert str(captured["path"]).endswith("/ApplyMatrix")
    assert captured["body"]["MatrixId"] == 77
    assert captured["body"]["VendingMachineId"] == 1001


def test_send_command_sends_command_object() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ResultCode": 0})

    _client(handler).send_command(
        vending_machine_id=1001,
        command_code=KitMatrixCommandCode.LOAD_MATRIX,
    )
    assert captured["body"]["Command"] == {"CommandCode": 3, "VendingMachineId": 1001}


def test_get_vending_machines_parses_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.path).endswith("/GetVendingMachines")
        return httpx.Response(
            200,
            json={
                "ResultCode": 0,
                "VendingMachines": [
                    {"VendingMachineId": 1001, "VendingMachineName": "Аппарат [512]"},
                ],
            },
        )

    records = _client(handler).get_vending_machines()
    assert records == [
        KitVendingMachineRecord(1001, "Аппарат [512]"),
    ]


def test_get_vm_states_parses_records_with_raw() -> None:
    item = {"VendingMachineId": 1001, "Statuses": "21,1"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url.path).endswith("/GetVMStates")
        return httpx.Response(200, json={"ResultCode": 0, "VendingMachines": [item]})

    records = _client(handler).get_vm_states()
    assert len(records) == 1
    assert records[0].vending_machine_id == 1001
    assert records[0].raw["Statuses"] == "21,1"
