from __future__ import annotations

from typing import Any

import httpx
from beartype import beartype

from src.config.kitvending import KitVendingSettings
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.integrations.kitvending.request_id_store import KitVendingRequestIdStore
from src.infrastructure.kitvending.deploy.models import (
    KitMatrixCommandCode,
    KitMatrixPosition,
    KitVendingMachineRecord,
    KitVMStateRecord,
)
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter


@beartype
class KitVendingDeployClient:
    def __init__(
        self,
        *,
        account: KitPlatformAccount,
        settings: KitVendingSettings,
        http_client: httpx.Client,
        request_id_store: KitVendingRequestIdStore,
        rate_limiter: SyncRateLimiter,
        backoff: SyncGlobalBackoff | None = None,
    ) -> None:
        self._api = KitVendingApiClient(
            account=account,
            settings=settings,
            http_client=http_client,
            request_id_store=request_id_store,
            rate_limiter=rate_limiter,
            backoff=backoff,
        )
        self.account = account
        self._settings = settings

    @beartype
    def _url(self, method: str) -> str:
        return f"{self._settings.api_base_url.rstrip('/')}/{method}"

    @beartype
    def _auth(self) -> dict[str, Any]:
        return self._api.build_auth(self._api.next_request_id())

    @beartype
    def create_pieces_matrix(
        self,
        matrix_name: str,
        positions: tuple[KitMatrixPosition, ...],
    ) -> int:
        response = self._api.send_post(
            self._url("CreatePiecesMatrix"),
            lambda: {
                "Auth": self._auth(),
                "MatrixName": matrix_name,
                "Positions": [position.to_request() for position in positions],
            },
        )
        return int(response["Id"])

    @beartype
    def apply_matrix(self, *, matrix_id: int, vending_machine_id: int) -> None:
        self._api.send_post(
            self._url("ApplyMatrix"),
            lambda: {
                "Auth": self._auth(),
                "MatrixId": matrix_id,
                "VendingMachineId": vending_machine_id,
            },
        )

    @beartype
    def send_command(
        self,
        *,
        vending_machine_id: int,
        command_code: KitMatrixCommandCode | int,
    ) -> None:
        self._api.send_post(
            self._url("SendCommand"),
            lambda: {
                "Auth": self._auth(),
                "Command": {
                    "CommandCode": int(command_code),
                    "VendingMachineId": vending_machine_id,
                },
            },
        )

    @beartype
    def get_vending_machines(self) -> list[KitVendingMachineRecord]:
        response = self._api.send_post(
            self._url("GetVendingMachines"),
            lambda: {"Auth": self._auth()},
        )
        machines = response["VendingMachines"]
        return [
            KitVendingMachineRecord(
                vending_machine_id=int(item["VendingMachineId"]),
                vending_machine_name=str(item["VendingMachineName"]),
            )
            for item in machines
        ]

    @beartype
    def get_vm_states(self) -> list[KitVMStateRecord]:
        response = self._api.send_post(
            self._url("GetVMStates"),
            lambda: {"Auth": self._auth()},
        )
        machines = response["VendingMachines"]
        return [
            KitVMStateRecord(
                vending_machine_id=int(item["VendingMachineId"]),
                raw=dict(item),
            )
            for item in machines
        ]
