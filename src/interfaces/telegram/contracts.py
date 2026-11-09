from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from aiogram import Bot
from beartype import beartype

from src.domain.ids import MachineId


@runtime_checkable
class TelegramDialogManager(Protocol):
    @property
    def dialog_data(self) -> dict[str, object]: ...

    def has_context(self) -> bool: ...

    def current_context(self) -> object: ...

    async def switch_to(self, state: object, /, **kwargs: object) -> None: ...

    async def update(self, /, **kwargs: object) -> None: ...

    async def show(self, /, **kwargs: object) -> None: ...


@runtime_checkable
class TelegramDialogBackgroundManager(Protocol):
    def fg(self) -> AbstractAsyncContextManager[TelegramDialogManager]: ...


@runtime_checkable
class TelegramDialogBackgroundFactory(Protocol):
    def bg(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int,
        load: bool = False,
        **kwargs: object,
    ) -> TelegramDialogBackgroundManager: ...


@beartype
@dataclass(frozen=True, slots=True)
class TelegramMachineOption:
    id: MachineId
    name: str
