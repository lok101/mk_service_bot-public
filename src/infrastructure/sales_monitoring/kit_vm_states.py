from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.application.matrix_automation import (
    extract_vending_machine_code,
    is_inactive_vending_machine_name,
)
from src.application.sales_monitoring.ports import KitMachineOfflineStatus
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.kitvending.deploy.models import (
    KitVendingMachineRecord,
    KitVMStateRecord,
)

# GetVMStates.DateTime — TZ полей Kit API (как sale_monitoring_bot KIT_API_TZ
# и Kit Shop SaleDateTime), не SALES_MONITORING_TZ и не Kit Vending
# sales-ingest (Asia/Yekaterinburg).
_KIT_API_DATETIME_TZ = ZoneInfo("Europe/Moscow")
_KIT_API_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"


@beartype
@dataclass(frozen=True, slots=True)
class KitVmStateSnapshot:
    kit_id: int
    machine_code: str | None
    last_ping_at: datetime | None
    is_offline: bool


class _DeployClientProtocol(Protocol):
    def get_vending_machines(self) -> list[KitVendingMachineRecord]: ...

    def get_vm_states(self) -> list[KitVMStateRecord]: ...


@beartype
def sales_poll_account(accounts: Sequence[KitPlatformAccount]) -> KitPlatformAccount:
    sales_poll = [
        account
        for account in accounts
        if account.platform is KitPlatform.KIT_VENDING
        and account.role is KitPlatformRole.SALES_POLL
    ]
    if len(sales_poll) > 1:
        raise ValueError("multiple sales_poll vending accounts")
    if not sales_poll:
        raise ValueError("sales_poll vending account required")
    return sales_poll[0]


@beartype
def head_account(accounts: Sequence[KitPlatformAccount]) -> KitPlatformAccount:
    return sales_poll_account(accounts)


@beartype
def parse_vm_state_ping(raw: Mapping[str, object]) -> datetime | None:
    value = raw.get("DateTime")
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        dt = datetime.strptime(stripped, _KIT_API_DATETIME_FORMAT)
    except ValueError:
        return None
    return dt.replace(tzinfo=_KIT_API_DATETIME_TZ)


@beartype
def is_offline_by_ping(
    *,
    last_ping: datetime | None,
    now: datetime,
    threshold_minutes: int,
) -> bool:
    if last_ping is None:
        return True
    return (now - last_ping) >= timedelta(minutes=threshold_minutes)


@beartype
def code_to_kit_id_map(
    machines: Sequence[KitVendingMachineRecord],
) -> dict[str, int]:
    mapping: dict[str, int] = {}
    ambiguous: set[str] = set()
    for record in machines:
        name = record.vending_machine_name
        if is_inactive_vending_machine_name(name):
            continue
        code = extract_vending_machine_code(name)
        if code is None:
            continue
        if code in ambiguous:
            continue
        existing = mapping.get(code)
        if existing is None:
            mapping[code] = record.vending_machine_id
            continue
        if existing != record.vending_machine_id:
            del mapping[code]
            ambiguous.add(code)
    return mapping


@beartype
class HeadKitVmStatesReader:
    """GetVMStates / GetVendingMachines only via sales_poll account."""

    def __init__(
        self,
        *,
        accounts: Sequence[KitPlatformAccount],
        deploy_client_factory: Callable[[KitPlatformAccount], _DeployClientProtocol],
    ) -> None:
        self._client = deploy_client_factory(sales_poll_account(accounts))

    @beartype
    def list_states(
        self,
        *,
        now: datetime,
        threshold_minutes: int,
    ) -> tuple[KitVmStateSnapshot, ...]:
        machines = self._client.get_vending_machines()
        code_by_kit_id = {
            record.vending_machine_id: extract_vending_machine_code(record.vending_machine_name)
            for record in machines
            if not is_inactive_vending_machine_name(record.vending_machine_name)
        }
        snapshots: list[KitVmStateSnapshot] = []
        for state in self._client.get_vm_states():
            last_ping = parse_vm_state_ping(state.raw)
            snapshots.append(
                KitVmStateSnapshot(
                    kit_id=state.vending_machine_id,
                    machine_code=code_by_kit_id.get(state.vending_machine_id),
                    last_ping_at=last_ping,
                    is_offline=is_offline_by_ping(
                        last_ping=last_ping,
                        now=now,
                        threshold_minutes=threshold_minutes,
                    ),
                )
            )
        return tuple(snapshots)

    @beartype
    def resolve_kit_ids(self) -> dict[str, int]:
        return code_to_kit_id_map(self._client.get_vending_machines())

    @beartype
    def statuses_for(
        self,
        *,
        machine_codes: Sequence[str],
        now: datetime,
        threshold_minutes: int,
    ) -> tuple[KitMachineOfflineStatus, ...]:
        kit_by_code = self.resolve_kit_ids()
        state_by_kit_id = {
            snapshot.kit_id: snapshot
            for snapshot in self.list_states(now=now, threshold_minutes=threshold_minutes)
        }
        result: list[KitMachineOfflineStatus] = []
        for code in machine_codes:
            kit_id = kit_by_code.get(code)
            if kit_id is None:
                result.append(
                    KitMachineOfflineStatus(
                        machine_code=code,
                        kit_id=None,
                        is_offline=True,
                        last_ping_at=None,
                    )
                )
                continue
            snapshot = state_by_kit_id.get(kit_id)
            if snapshot is None:
                result.append(
                    KitMachineOfflineStatus(
                        machine_code=code,
                        kit_id=kit_id,
                        is_offline=True,
                        last_ping_at=None,
                    )
                )
                continue
            result.append(
                KitMachineOfflineStatus(
                    machine_code=code,
                    kit_id=kit_id,
                    is_offline=snapshot.is_offline,
                    last_ping_at=snapshot.last_ping_at,
                )
            )
        return tuple(result)
