from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from time import monotonic as _monotonic
from time import sleep as _sleep
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.matrix_automation import (
    MatrixDeployer,
    MatrixDeployFailureReason,
    MatrixDeployPayload,
    MatrixDeployResult,
)
from src.infrastructure.kitvending.deploy.models import (
    KitMatrixCommandCode,
    KitMatrixPosition,
    KitVendingMachineRecord,
    KitVMStateRecord,
    build_matrix_position,
)
from src.infrastructure.kitvending.deploy.resolution import (
    ResolvedOwner,
    resolve_active_owner,
)

_MATRIX_LOADED_STATUS = 21
_logger = logging.getLogger(__name__)
_DeployPhase = Literal["load", "apply"]


@runtime_checkable
class KitDeployClientProtocol(Protocol):
    def get_vending_machines(self) -> list[KitVendingMachineRecord]: ...

    def create_pieces_matrix(
        self,
        matrix_name: str,
        positions: tuple[KitMatrixPosition, ...],
    ) -> int: ...

    def apply_matrix(self, *, matrix_id: int, vending_machine_id: int) -> None: ...

    def send_command(
        self,
        *,
        vending_machine_id: int,
        command_code: KitMatrixCommandCode | int,
    ) -> None: ...

    def get_vm_states(self) -> list[KitVMStateRecord]: ...


@beartype
@dataclass(slots=True)
class BatchMatrixDeployCoordinator(MatrixDeployer):
    clients: Sequence[KitDeployClientProtocol]
    blocking_label: str
    display_timezone: tzinfo
    now: Callable[[], datetime]
    load_timeout_seconds: int
    apply_timeout_seconds: int
    status_poll_interval_seconds: int
    command_send_delay_seconds: int
    poll_api_max_retries: int
    retry_send_command_delay_seconds: int
    sleep: Callable[[float], None] = _sleep
    monotonic: Callable[[], float] = _monotonic

    @beartype
    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]:
        return [self._deploy_one(payload) for payload in payloads]

    def _deploy_one(self, payload: MatrixDeployPayload) -> MatrixDeployResult:
        client, vm, resolve_reason = self._resolve_client(payload.machine_code)
        if client is None or vm is None:
            reason: MatrixDeployFailureReason = resolve_reason or "machine_not_found_in_kit"
            return self._failed(payload, reason)

        positions = self._positions(payload)
        matrix_name = self._matrix_name(payload)
        try:
            matrix_id = client.create_pieces_matrix(matrix_name, positions)
        except Exception as exc:
            _logger.warning(
                "kitvending_matrix_upload_failed",
                extra={
                    "machine_code": payload.machine_code,
                    "logical_matrix_name": payload.logical_matrix_name,
                    "exception_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return self._failed(payload, "upload_failed")

        try:
            client.apply_matrix(matrix_id=matrix_id, vending_machine_id=vm.vending_machine_id)
        except Exception as exc:
            _logger.warning(
                "kitvending_matrix_bind_failed",
                extra={
                    "machine_code": payload.machine_code,
                    "logical_matrix_name": payload.logical_matrix_name,
                    "matrix_id": matrix_id,
                    "exception_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return self._failed(payload, "bind_failed")

        if not self._send_command_with_retry(
            client,
            vending_machine_id=vm.vending_machine_id,
            command_code=KitMatrixCommandCode.LOAD_MATRIX,
        ):
            return self._failed(payload, "load_timeout")

        if not self._wait_for_state(client, vm.vending_machine_id, phase="load"):
            return self._failed(payload, "load_timeout")

        self.sleep(self.command_send_delay_seconds)

        if not self._send_command_with_retry(
            client,
            vending_machine_id=vm.vending_machine_id,
            command_code=KitMatrixCommandCode.APPLY_MATRIX,
        ):
            return self._failed(payload, "apply_timeout")

        if not self._wait_for_state(client, vm.vending_machine_id, phase="apply"):
            return self._failed(payload, "apply_timeout")

        return MatrixDeployResult(
            payload.logical_matrix_name,
            payload.machine_code,
            "applied",
            None,
            kit_matrix_id=matrix_id,
            vending_machine_id=vm.vending_machine_id,
            kit_matrix_name=matrix_name,
        )

    def _matrix_name(self, payload: MatrixDeployPayload) -> str:
        date = self.now().astimezone(self.display_timezone).date().isoformat()
        return f"{payload.logical_matrix_name.strip()}_{payload.machine_code.strip()}_{date}"

    def _positions(self, payload: MatrixDeployPayload) -> tuple[KitMatrixPosition, ...]:
        return tuple(
            build_matrix_position(
                line_number=line.line_number,
                product_name=line.product_name,
                product_code=line.product_code,
                deploy_price=line.deploy_price,
                capacity=line.capacity,
                blocking_label=self.blocking_label,
            )
            for line in payload.lines
        )

    def _resolve_client(
        self,
        machine_code: str,
    ) -> tuple[
        KitDeployClientProtocol | None,
        KitVendingMachineRecord | None,
        MatrixDeployFailureReason | None,
    ]:
        accounts: list[tuple[int, tuple[KitVendingMachineRecord, ...]]] = []
        for index, client in enumerate(self.clients):
            try:
                machines = client.get_vending_machines()
            except Exception as exc:
                self._log_lookup_failed(machine_code=machine_code, index=index, exc=exc)
                return None, None, "kit_machine_lookup_failed"
            accounts.append((index, tuple(machines)))
        outcome = resolve_active_owner(accounts, machine_code)
        if isinstance(outcome, ResolvedOwner):
            self._log_resolved(machine_code=machine_code, outcome=outcome)
            return self.clients[outcome.account_index], outcome.record, None
        return None, None, outcome

    @staticmethod
    def _account_ref(index: int) -> tuple[str, str]:
        role = "head" if index == 0 else "child"
        return role, f"{role}[{index}]"

    def _log_lookup_failed(
        self,
        *,
        machine_code: str,
        index: int,
        exc: Exception,
    ) -> None:
        role, ref = self._account_ref(index)
        _logger.warning(
            "kitvending_machine_lookup_failed",
            extra={
                "machine_code": machine_code,
                "account_role": role,
                "account_index": index,
                "account_ref": ref,
                "exception_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    def _log_resolved(self, *, machine_code: str, outcome: ResolvedOwner) -> None:
        role, ref = self._account_ref(outcome.account_index)
        _logger.info(
            "kitvending_machine_resolved",
            extra={
                "machine_code": machine_code,
                "vending_machine_id": outcome.record.vending_machine_id,
                "account_role": role,
                "account_index": outcome.account_index,
                "account_ref": ref,
                "head_shadow": outcome.head_shadow,
            },
        )

    def _send_command_with_retry(
        self,
        client: KitDeployClientProtocol,
        *,
        vending_machine_id: int,
        command_code: KitMatrixCommandCode,
    ) -> bool:
        attempts = self.poll_api_max_retries
        for attempt in range(attempts):
            try:
                client.send_command(
                    vending_machine_id=vending_machine_id,
                    command_code=command_code,
                )
                return True
            except Exception:
                if attempt < attempts - 1:
                    self.sleep(self.retry_send_command_delay_seconds)
        return False

    def _wait_for_state(
        self,
        client: KitDeployClientProtocol,
        vending_machine_id: int,
        *,
        phase: _DeployPhase,
    ) -> bool:
        timeout_seconds = (
            self.load_timeout_seconds if phase == "load" else self.apply_timeout_seconds
        )
        deadline = self.monotonic() + timeout_seconds
        transient_failures = 0
        while self.monotonic() < deadline:
            try:
                states = client.get_vm_states()
            except Exception:
                transient_failures += 1
                if transient_failures >= self.poll_api_max_retries:
                    return False
                self.sleep(self.status_poll_interval_seconds)
                continue
            transient_failures = 0
            if self._state_success(states, vending_machine_id, phase=phase):
                return True
            self.sleep(self.status_poll_interval_seconds)
        return False

    def _state_success(
        self,
        states: list[KitVMStateRecord],
        vending_machine_id: int,
        *,
        phase: _DeployPhase,
    ) -> bool:
        for state in states:
            if state.vending_machine_id != vending_machine_id:
                continue
            codes = _parse_status_codes(state.raw)
            if phase == "load":
                return _MATRIX_LOADED_STATUS in codes
            return _MATRIX_LOADED_STATUS not in codes
        return False

    def _failed(
        self,
        payload: MatrixDeployPayload,
        reason: MatrixDeployFailureReason,
    ) -> MatrixDeployResult:
        return MatrixDeployResult(
            payload.logical_matrix_name,
            payload.machine_code,
            "failed",
            reason,
        )


def _parse_status_codes(raw: dict[str, object]) -> set[int]:
    statuses = raw.get("Statuses", "")
    if statuses is None:
        return set()
    text = str(statuses).strip()
    if not text:
        return set()
    codes: set[int] = set()
    for part in text.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            codes.add(int(token))
        except ValueError:
            continue
    return codes
