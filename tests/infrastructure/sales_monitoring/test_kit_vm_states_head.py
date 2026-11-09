from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tests.infrastructure.kitvending.platform_account_helpers import make_platform_account

from src.application.master_data.companies import KitPlatformRole
from src.application.sales_monitoring.ports import KitMachineOfflineStatus
from src.infrastructure.integrations.kitvending.platform_accounts import KitPlatformAccount
from src.infrastructure.kitvending.deploy.models import (
    KitVendingMachineRecord,
    KitVMStateRecord,
)
from src.infrastructure.sales_monitoring.kit_vm_states import (
    HeadKitVmStatesReader,
    code_to_kit_id_map,
    head_account,
    is_offline_by_ping,
    parse_vm_state_ping,
    sales_poll_account,
)

_EKB = ZoneInfo("Asia/Yekaterinburg")
_HEAD = make_platform_account(
    account_key="head",
    company_id=1,
    kit_company_id=1,
    login="head-login",
    password="head-pass",
    role=KitPlatformRole.SALES_POLL,
)
_CHILD = make_platform_account(
    account_key="child",
    company_id=2,
    kit_company_id=2,
    login="child-login",
    password="child-pass",
    role=KitPlatformRole.CATALOG,
)


class _FakeDeployClient:
    def __init__(self, account: KitPlatformAccount) -> None:
        self.account = account
        self.machines: list[KitVendingMachineRecord] = []
        self.states: list[KitVMStateRecord] = []

    def get_vending_machines(self) -> list[KitVendingMachineRecord]:
        return list(self.machines)

    def get_vm_states(self) -> list[KitVMStateRecord]:
        return list(self.states)


def test_offline_poll_uses_head_account_only() -> None:
    factory_calls: list[str] = []
    clients: dict[str, _FakeDeployClient] = {}

    def factory(account: KitPlatformAccount) -> _FakeDeployClient:
        factory_calls.append(account.login)
        client = _FakeDeployClient(account)
        clients[account.login] = client
        return client

    reader = HeadKitVmStatesReader(
        accounts=(_HEAD, _CHILD),
        deploy_client_factory=factory,
    )
    head_client = clients[_HEAD.login]
    head_client.machines = [
        KitVendingMachineRecord(101, "Локация [101]"),
    ]
    head_client.states = [
        KitVMStateRecord(101, {"DateTime": "27.07.2026 10:00:00"}),
    ]

    states = reader.list_states(
        now=datetime(2026, 7, 27, 10, 30, tzinfo=_EKB),
        threshold_minutes=25,
    )

    assert factory_calls == ["head-login"]
    assert "child-login" not in factory_calls
    assert len(states) == 1
    assert states[0].kit_id == 101
    assert states[0].machine_code == "101"


def test_parse_vm_state_ping_uses_kit_api_moscow_tz() -> None:
    """GetVMStates.DateTime — TZ Kit API (Europe/Moscow), не SALES_MONITORING_TZ."""
    moscow = ZoneInfo("Europe/Moscow")
    parsed = parse_vm_state_ping({"DateTime": "27.07.2026 10:00:00"})
    assert parsed == datetime(2026, 7, 27, 10, 0, 0, tzinfo=moscow)


def test_missing_or_invalid_datetime_counts_as_offline() -> None:
    now = datetime(2026, 7, 27, 10, 30, tzinfo=_EKB)
    assert parse_vm_state_ping({}) is None
    assert parse_vm_state_ping({"DateTime": "not-a-date"}) is None
    assert is_offline_by_ping(last_ping=None, now=now, threshold_minutes=25) is True


def test_head_account_selects_sales_poll() -> None:
    accounts: Sequence[KitPlatformAccount] = (_HEAD, _CHILD)
    assert sales_poll_account(accounts) is _HEAD
    assert head_account(accounts) is _HEAD


def test_ping_within_threshold_is_online() -> None:
    now = datetime(2026, 7, 27, 10, 30, tzinfo=_EKB)
    last_ping = now - timedelta(minutes=24)
    assert is_offline_by_ping(last_ping=last_ping, now=now, threshold_minutes=25) is False
    assert (
        is_offline_by_ping(
            last_ping=now - timedelta(minutes=25),
            now=now,
            threshold_minutes=25,
        )
        is True
    )


def test_recent_moscow_ping_not_offline_vs_ekb_now() -> None:
    """Регресс: привязка DateTime к EKB вместо Moscow даёт ложный offline (+2ч)."""
    moscow = ZoneInfo("Europe/Moscow")
    now = datetime(2026, 7, 6, 17, 0, tzinfo=_EKB)
    ping = parse_vm_state_ping({"DateTime": "06.07.2026 15:00:00"})
    assert ping == datetime(2026, 7, 6, 15, 0, tzinfo=moscow)
    assert is_offline_by_ping(last_ping=ping, now=now, threshold_minutes=25) is False


def test_statuses_for_online_when_moscow_ping_fresh() -> None:
    def factory(account: KitPlatformAccount) -> _FakeDeployClient:
        client = _FakeDeployClient(account)
        client.machines = [KitVendingMachineRecord(1001, "Локация [101]")]
        client.states = [
            KitVMStateRecord(1001, {"DateTime": "06.07.2026 15:00:00", "Statuses": "1"}),
        ]
        return client

    reader = HeadKitVmStatesReader(accounts=(_HEAD,), deploy_client_factory=factory)
    statuses = reader.statuses_for(
        machine_codes=("101",),
        now=datetime(2026, 7, 6, 17, 10, tzinfo=_EKB),
        threshold_minutes=25,
    )
    assert len(statuses) == 1
    assert statuses[0].kit_id == 1001
    assert statuses[0].is_offline is False


def test_ambiguous_machine_code_omitted_from_kit_map() -> None:
    machines = (
        KitVendingMachineRecord(1001, "Локация A [101]"),
        KitVendingMachineRecord(1002, "Локация B [101]"),
    )
    assert "101" not in code_to_kit_id_map(machines)

    factory_calls: list[str] = []

    def factory(account: KitPlatformAccount) -> _FakeDeployClient:
        factory_calls.append(account.login)
        client = _FakeDeployClient(account)
        client.machines = list(machines)
        client.states = [
            KitVMStateRecord(1001, {"DateTime": "27.07.2026 10:00:00"}),
            KitVMStateRecord(1002, {"DateTime": "27.07.2026 10:00:00"}),
        ]
        return client

    reader = HeadKitVmStatesReader(accounts=(_HEAD,), deploy_client_factory=factory)
    statuses = reader.statuses_for(
        machine_codes=("101",),
        now=datetime(2026, 7, 27, 10, 30, tzinfo=_EKB),
        threshold_minutes=25,
    )
    assert len(statuses) == 1
    assert statuses[0].machine_code == "101"
    assert statuses[0].kit_id is None
    assert factory_calls == ["head-login"]


def test_cyrillic_inactive_marker_does_not_conflict_with_active_same_code() -> None:
    machines = (
        KitVendingMachineRecord(
            982345,
            "[ Х ] [166] - ТЦ Космос, 1 эт | Космонавтов, 54",
        ),
        KitVendingMachineRecord(
            1018504,
            "[166] - Семейная клиника | 8 марта, 194",
        ),
    )
    assert code_to_kit_id_map(machines) == {"166": 1018504}

    def factory(account: KitPlatformAccount) -> _FakeDeployClient:
        client = _FakeDeployClient(account)
        client.machines = list(machines)
        client.states = [
            KitVMStateRecord(
                1018504,
                {"DateTime": "27.07.2026 10:00:00"},
            ),
        ]
        return client

    reader = HeadKitVmStatesReader(accounts=(_HEAD,), deploy_client_factory=factory)
    statuses = reader.statuses_for(
        machine_codes=("166",),
        now=datetime(2026, 7, 27, 10, 30, tzinfo=_EKB),
        threshold_minutes=25,
    )
    assert statuses == (
        KitMachineOfflineStatus(
            machine_code="166",
            kit_id=1018504,
            is_offline=False,
            last_ping_at=datetime(2026, 7, 27, 10, 0, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        ),
    )
