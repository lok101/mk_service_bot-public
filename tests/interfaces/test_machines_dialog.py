from __future__ import annotations

from src.application.machine_operations.use_cases import LocationListScope
from src.domain.ids import TechnicianId
from src.domain.system_user import BotRole, SystemUser, SystemUserId
from src.interfaces.telegram.machines.access import (
    can_show_machine_list,
    can_use_bot,
    maintenance_state_for_bot_user,
    requires_revision_check_before_maintenance,
    technician_id_for_machine_operations,
)
from src.interfaces.telegram.machines.getters import _machines_list_headline
from src.interfaces.telegram.machines.location_scope import start_data_for_scope
from src.interfaces.telegram.machines.state import MachineListState

_TEST_BOT_USER = SystemUser(
    user_id=SystemUserId("10001"),
    name="Test",
    role=BotRole.TECHNICIAN,
    is_active=True,
    telegram_user_id=1,
    technician_id=TechnicianId("001"),
    company_roles=frozenset(),
)


def _user(*, role: BotRole, active: bool = True) -> SystemUser:
    return SystemUser(
        user_id=SystemUserId("u-none"),
        name="Бухгалтер",
        role=role,
        is_active=active,
        telegram_user_id=9001,
        technician_id=None,
        company_roles=frozenset(),
    )


def test_can_use_bot_false_for_none_role() -> None:
    assert can_use_bot(_user(role=BotRole.NONE)) is False


def test_can_show_machine_list_false_for_none_role() -> None:
    assert can_show_machine_list(_user(role=BotRole.NONE)) is False


def test_maintenance_state_for_none_is_not_admin() -> None:
    assert maintenance_state_for_bot_user(_user(role=BotRole.NONE)) is MachineListState.maintenance


def test_requires_revision_check_true_for_none() -> None:
    assert requires_revision_check_before_maintenance(_user(role=BotRole.NONE)) is True


def test_requires_revision_check_for_technician() -> None:
    assert requires_revision_check_before_maintenance(_TEST_BOT_USER) is True


def test_skips_revision_check_for_administrator_without_technician_id() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=None,
        company_roles=frozenset(),
    )

    assert requires_revision_check_before_maintenance(admin) is False


def test_requires_revision_check_for_administrator_with_technician_id() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=TechnicianId("001"),
        company_roles=frozenset(),
    )

    assert requires_revision_check_before_maintenance(admin) is True


def test_requires_revision_check_when_user_unknown() -> None:
    assert requires_revision_check_before_maintenance(None) is True


def test_maintenance_state_for_administrator() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=None,
        company_roles=frozenset(),
    )

    assert maintenance_state_for_bot_user(admin) is MachineListState.admin_maintenance


def test_maintenance_state_for_technician() -> None:
    assert maintenance_state_for_bot_user(_TEST_BOT_USER) is MachineListState.maintenance


def test_maintenance_state_defaults_to_technician_window_when_user_unknown() -> None:
    assert maintenance_state_for_bot_user(None) is MachineListState.maintenance


def test_can_use_bot_requires_active_account() -> None:
    inactive = SystemUser(
        user_id=SystemUserId("10003"),
        name="Inactive",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=3,
        technician_id=TechnicianId("003"),
        company_roles=frozenset(),
    )

    assert can_use_bot(_TEST_BOT_USER) is True
    assert can_use_bot(inactive) is False


def test_can_show_machine_list_denies_inactive_technician() -> None:
    inactive = SystemUser(
        user_id=SystemUserId("10003"),
        name="Inactive",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=3,
        technician_id=TechnicianId("003"),
        company_roles=frozenset(),
    )

    assert can_show_machine_list(_TEST_BOT_USER) is True
    assert can_show_machine_list(inactive) is False


def test_can_show_machine_list_denies_inactive_administrator() -> None:
    inactive_admin = SystemUser(
        user_id=SystemUserId("10004"),
        name="Inactive Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=False,
        telegram_user_id=4,
        technician_id=None,
        company_roles=frozenset(),
    )

    assert can_show_machine_list(inactive_admin) is False


def test_inactive_user_payload_includes_profile_and_inactive_headline() -> None:
    from src.interfaces.telegram.machines.getters import (
        _INACTIVE_HEADLINE,
        inactive_user_payload,
    )

    inactive = SystemUser(
        user_id=SystemUserId("10005"),
        name="Роман",
        role=BotRole.TECHNICIAN,
        is_active=False,
        telegram_user_id=444555666,
        technician_id=TechnicianId("002"),
        company_roles=frozenset(),
    )

    payload = inactive_user_payload(inactive)

    assert payload["headline"] == _INACTIVE_HEADLINE
    assert payload["user_is_active"] is False
    assert "Роман" in str(payload["machines_screen_text"])


def test_machines_list_payload_includes_visit_status_legend() -> None:
    from src.interfaces.telegram.machines.getters import (
        _VISIT_STATUS_LEGEND,
        machines_list_payload,
    )

    payload = machines_list_payload(_TEST_BOT_USER, [], scope=LocationListScope.OWN)

    text = str(payload["machines_screen_text"])
    assert _VISIT_STATUS_LEGEND in text
    assert "Выберите аппарат. Всего доступно: 0" in text
    assert "Test" in text


def test_machines_list_headline_for_technician_own_scope() -> None:
    headline = _machines_list_headline(
        _TEST_BOT_USER,
        scope=LocationListScope.OWN,
        count=3,
    )

    assert headline == "Выберите аппарат. Всего доступно: 3"


def test_machines_list_headline_for_technician_others_scope() -> None:
    headline = _machines_list_headline(
        _TEST_BOT_USER,
        scope=LocationListScope.OTHERS,
        count=1,
    )

    assert headline == "Другие локации. Всего доступно: 1"


def test_machines_list_headline_for_administrator_without_technician_id() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=None,
        company_roles=frozenset(),
    )

    headline = _machines_list_headline(
        admin,
        scope=LocationListScope.OTHERS,
        count=5,
    )

    assert headline == "Все локации. Всего доступно: 5"


def test_start_data_for_scope() -> None:
    assert start_data_for_scope(LocationListScope.OWN) == {"location_scope": "own"}
    assert start_data_for_scope(LocationListScope.OTHERS) == {
        "location_scope": "others",
    }


def test_technician_id_for_machine_operations_uses_bot_user_technician_id() -> None:
    assert technician_id_for_machine_operations(_TEST_BOT_USER) == TechnicianId("001")


def test_technician_id_for_machine_operations_for_administrator_with_technician_id() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=TechnicianId("002"),
        company_roles=frozenset(),
    )

    assert technician_id_for_machine_operations(admin) == TechnicianId("002")


def test_technician_id_for_machine_operations_for_administrator_without_technician_id() -> None:
    admin = SystemUser(
        user_id=SystemUserId("10002"),
        name="Admin",
        role=BotRole.ADMINISTRATOR,
        is_active=True,
        telegram_user_id=2,
        technician_id=None,
        company_roles=frozenset(),
    )

    assert technician_id_for_machine_operations(admin) is None


def test_technician_id_for_machine_operations_when_user_unknown() -> None:
    assert technician_id_for_machine_operations(None) is None
