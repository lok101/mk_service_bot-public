from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from aiogram_dialog import DialogManager
from beartype import beartype

from src.application.machine_operations import LocationListScope
from src.application.master_data import MachineKind
from src.domain.calendar import operational_day
from src.domain.ids import MachineId, TechnicianId
from src.domain.models import VendingMachine
from src.domain.system_user import BotRole, SystemUser
from src.interfaces.telegram.contracts import TelegramMachineOption
from src.interfaces.telegram.machines.access import (
    can_show_machine_list,
    can_use_bot,
    list_machines_for_bot_user,
    technician_id_for_machine_operations,
)
from src.interfaces.telegram.machines.bot_user import (
    bot_user_ui_fields,
    get_event_user,
    resolve_bot_user,
)
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.location_scope import location_scope_from_manager
from src.interfaces.telegram.machines.visit_options import machine_options_from_visits

_UNKNOWN_USER_HEADLINE = "Не удалось найти пользователя по вашему Telegram ID."
_RESTRICTED_HEADLINE = "Список аппаратов пока недоступен для вашей учётной записи."
_INACTIVE_HEADLINE = "Ваша учётная запись неактивна. Обратитесь к администратору."
_VISIT_STATUS_LEGEND = (
    "⏺️ - нужно обслужить сегодня.\n"
    "✅ - обслужено сегодня.\n"
    "✴️ - срочный, внеплановый выезд.\n"
    "‼️ - просроченное обслуживание.\n"
    "⚖️ - сегодня обязательна инвентаризация."
)


@beartype
def unknown_user_payload() -> dict[str, object]:
    return {
        "headline": _UNKNOWN_USER_HEADLINE,
        "machines_screen_text": _UNKNOWN_USER_HEADLINE,
        "machines": [],
        "machines_count": 0,
        "has_machines": False,
        "is_known_technician": False,
        **bot_user_ui_fields(None),
    }


@beartype
def inactive_user_payload(bot_user: SystemUser) -> dict[str, object]:
    return {
        "headline": _INACTIVE_HEADLINE,
        "machines_screen_text": f"{bot_user.profile_line_ru}\n\n{_INACTIVE_HEADLINE}",
        "machines": [],
        "machines_count": 0,
        "has_machines": False,
        "is_known_technician": False,
        **bot_user_ui_fields(bot_user),
    }


@beartype
def restricted_user_payload(bot_user: SystemUser) -> dict[str, object]:
    return {
        "headline": _RESTRICTED_HEADLINE,
        "machines_screen_text": f"{bot_user.profile_line_ru}\n\n{_RESTRICTED_HEADLINE}",
        "machines": [],
        "machines_count": 0,
        "has_machines": False,
        "is_known_technician": False,
        **bot_user_ui_fields(bot_user),
    }


@beartype
def _machines_list_headline(
    bot_user: SystemUser,
    *,
    scope: LocationListScope,
    count: int,
) -> str:
    if bot_user.role is BotRole.ADMINISTRATOR and bot_user.technician_id is None:
        return f"Все локации. Всего доступно: {count}"

    if scope is LocationListScope.OTHERS:
        return f"Другие локации. Всего доступно: {count}"

    return f"Выберите аппарат. Всего доступно: {count}"


@beartype
def machines_list_payload(
    bot_user: SystemUser,
    options: list[TelegramMachineOption],
    *,
    scope: LocationListScope = LocationListScope.OWN,
) -> dict[str, object]:
    headline = _machines_list_headline(bot_user, scope=scope, count=len(options))
    parts = [bot_user.profile_line_ru, _VISIT_STATUS_LEGEND, headline]

    return {
        "headline": headline,
        "machines_screen_text": "\n\n".join(parts),
        "machines": options,
        "machines_count": len(options),
        "has_machines": len(options) > 0,
        "is_known_technician": True,
        **bot_user_ui_fields(bot_user),
    }


DialogDataGetter = Callable[..., Awaitable[dict[str, object]]]


def build_machines_getter(deps: MachineListDeps) -> DialogDataGetter:
    async def get_machines(
        dialog_manager: DialogManager,
        **kwargs: object,
    ) -> dict[str, object]:
        event_user = get_event_user(kwargs)
        if event_user is None:
            return unknown_user_payload()

        bot_user = await resolve_bot_user(deps, event_user.id)
        if bot_user is None:
            return unknown_user_payload()

        if not can_use_bot(bot_user):
            return inactive_user_payload(bot_user)

        if not can_show_machine_list(bot_user):
            return restricted_user_payload(bot_user)

        scope = location_scope_from_manager(dialog_manager)
        machines = list_machines_for_bot_user(deps, bot_user, scope=scope)
        visits = [
            visit for machine in machines for visit in deps.visit_store.list_for_machine(machine.id)
        ]
        ops_day = operational_day(
            datetime.now(tz=UTC),
            deps.service_display_timezone,
            deps.service_day_end_hour,
        )
        technician_id = technician_id_for_machine_operations(bot_user)
        revision_due_ids = _coffee_revision_due_machine_ids(
            deps,
            machines=tuple(machines),
            technician_id=technician_id,
        )
        options = machine_options_from_visits(
            tuple(machines),
            tuple(visits),
            ops_day=ops_day,
            revision_due_machine_ids=revision_due_ids,
        )
        return machines_list_payload(
            bot_user,
            options,
            scope=scope,
        )

    return get_machines


@beartype
def _coffee_revision_due_machine_ids(
    deps: MachineListDeps,
    *,
    machines: tuple[VendingMachine, ...],
    technician_id: TechnicianId | None,
) -> frozenset[MachineId]:
    # Read aggregate phase only — do not call GetServiceCapabilities (mints form tokens).
    if technician_id is None or deps.machine_kind_lookup is None:
        return frozenset()
    due: set[MachineId] = set()
    for machine in machines:
        if deps.machine_kind_lookup.kind_of(machine.id.value) is not MachineKind.COFFEE:
            continue
        aggregate = deps.machine_operations.get(machine.id)
        if aggregate.responsibility_phase(technician_id) == "awaiting_handover":
            due.add(machine.id)
    return frozenset(due)
