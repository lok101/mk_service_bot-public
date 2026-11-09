from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.micromarket_loading.move_command import (
    MicromarketLoadingMoveCommandStore,
)
from src.application.micromarket_loading.move_gateway import (
    MicromarketMoveGateway,
    MoveAlreadyGone,
    MoveDeleteFailed,
)
from src.domain.events import DomainEvent
from src.domain.micromarket_loading.move_command_event import MicromarketLoadingMoveCommandRequested

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingMoveOutboxHandler:
    command_store: MicromarketLoadingMoveCommandStore
    move_client: MicromarketMoveGateway
    clock: Callable[[], datetime]

    @beartype
    def process(self, event: DomainEvent) -> None:
        if not isinstance(event, MicromarketLoadingMoveCommandRequested):
            raise TypeError(type(event).__name__)
        command = self.command_store.get(event.command_id)
        if command is None:
            _logger.warning(
                "micromarket_loading_move_command_missing command_id=%s",
                event.command_id,
            )
            return
        if command.status != "pending":
            return
        try:
            if command.kind == "create":
                if command.order_id is None or command.machine_code is None:
                    raise ValueError("create command missing order_id or machine_code")
                move_id = self.move_client.create_move(
                    order_id=command.order_id,
                    machine_code=command.machine_code,
                    positions=command.positions,
                )
                if not self.command_store.mark_succeeded(
                    command_id=command.command_id,
                    move_id=move_id,
                ):
                    _logger.info(
                        "micromarket_loading_move_command_already_terminal command_id=%s",
                        command.command_id,
                    )
                return
            if command.kind == "delete":
                if command.move_id is None:
                    raise ValueError("delete command missing move_id")
                try:
                    self.move_client.delete_move(move_id=command.move_id)
                except MoveAlreadyGone:
                    pass
                except MoveDeleteFailed as error:
                    raise RuntimeError(str(error)) from error
                self.command_store.mark_succeeded(command_id=command.command_id)
                return
            if command.kind == "stale_check":
                if command.order_id is None:
                    raise ValueError("stale_check command missing order_id")
                stale = self.move_client.existing_move_for_order_is_stale(
                    order_id=command.order_id,
                    now=self.clock(),
                )
                self.command_store.mark_succeeded(
                    command_id=command.command_id,
                    stale=stale,
                )
                return
            raise ValueError(f"unknown move command kind: {command.kind}")
        except Exception as error:
            _logger.exception(
                "micromarket_loading_move_command_failed command_id=%s",
                event.command_id,
            )
            self.command_store.mark_failed(
                command_id=command.command_id,
                error=str(error),
            )
