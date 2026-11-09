from __future__ import annotations

import asyncio

from aiogram.types import User
from beartype import beartype

from src.domain.system_user import SystemUser
from src.interfaces.telegram.machines.deps import MachineDialogDeps, MachineListDeps


@beartype
def get_event_user(kwargs: dict[str, object]) -> User | None:
    event_from_user = kwargs.get("event_from_user")
    if isinstance(event_from_user, User):
        return event_from_user

    return None


@beartype
def bot_user_ui_fields(bot_user: SystemUser | None) -> dict[str, object]:
    if bot_user is None:
        return {
            "is_known_user": False,
            "user_name": "",
            "user_role_label": "",
            "user_is_active": False,
            "user_status_label": "",
            "user_profile_line": "",
        }

    return {
        "is_known_user": True,
        "user_name": bot_user.name,
        "user_role_label": bot_user.role.label_ru,
        "user_is_active": bot_user.is_active,
        "user_status_label": bot_user.status_label_ru,
        "user_profile_line": bot_user.profile_line_ru,
    }


@beartype
async def resolve_bot_user(
    deps: MachineListDeps | MachineDialogDeps,
    telegram_user_id: int,
) -> SystemUser | None:
    return await asyncio.to_thread(
        deps.telegram_user_resolver.resolve,
        telegram_user_id,
    )
