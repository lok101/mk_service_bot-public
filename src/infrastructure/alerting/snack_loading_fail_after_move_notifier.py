from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from beartype import beartype

from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class TelegramSnackLoadingFailAfterMoveNotifier:
    bot_token: str
    chat_id: int
    _send: Callable[[str], None] | None = None

    @beartype
    def notify_fail_after_move(
        self,
        *,
        machine_code: str,
        move_id: str,
        run_id: str,
    ) -> None:
        text = (
            f"Snack loading fail-after-move: machine={machine_code} "
            f"move_id={move_id} run_id={run_id}"
        )
        try:
            if self._send is not None:
                self._send(text)
                return
            send_telegram_message(
                bot_token=self.bot_token,
                chat_id=self.chat_id,
                text=text,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "snack_loading_fail_after_move_alert_failed machine=%s move_id=%s error=%s",
                machine_code,
                move_id,
                exc,
            )
