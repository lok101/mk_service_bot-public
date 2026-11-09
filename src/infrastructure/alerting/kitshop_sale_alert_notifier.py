from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from beartype import beartype

from src.application.inventory_reconciliation.drain_kitshop_sales import KitShopAlertPhase
from src.application.product_identity import hold_alert_text
from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _hold_reason_label(reason: str) -> str:
    text = hold_alert_text(reason)
    if text is None:
        return reason
    return text


@beartype
@dataclass(slots=True)
class TelegramKitShopSaleAlertNotifier:
    bot_token: str
    chat_id: int
    cooldown_minutes: int
    now: Callable[[], datetime] = _utc_now
    _send: Callable[[str], None] | None = None
    _last_fingerprint: tuple[object, ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_sent_at: datetime | None = field(default=None, init=False, repr=False)

    @beartype
    def notify_held(self, *, count: int, reasons: Sequence[str]) -> None:
        sorted_reasons = tuple(sorted(reasons))
        fingerprint: tuple[object, ...] = ("held", *sorted_reasons)
        shown = tuple(_hold_reason_label(reason) for reason in sorted_reasons)
        held_text = f"Kit Shop sales: {count} held ({', '.join(shown)})."
        self._send_with_cooldown(fingerprint=fingerprint, text=held_text)

    @beartype
    def notify_phase_failed(
        self,
        *,
        phase: KitShopAlertPhase,
        exception_type: str,
    ) -> None:
        fingerprint: tuple[object, ...] = ("failed", phase, exception_type)
        failed_text = f"Kit Shop sales: {phase} failed ({exception_type})."
        self._send_with_cooldown(fingerprint=fingerprint, text=failed_text)

    @beartype
    def _send_with_cooldown(self, *, fingerprint: tuple[object, ...], text: str) -> None:
        sent_at = self.now()
        if (
            self._last_fingerprint == fingerprint
            and self._last_sent_at is not None
            and sent_at - self._last_sent_at < timedelta(minutes=self.cooldown_minutes)
        ):
            _logger.info(
                "kitshop_sales_alert_suppressed",
                extra={"fingerprint": fingerprint},
            )
            return

        try:
            if self._send is not None:
                self._send(text)
            else:
                send_telegram_message(
                    bot_token=self.bot_token,
                    chat_id=self.chat_id,
                    text=text,
                )
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "kitshop_sales_alert_failed",
                extra={"fingerprint": fingerprint, "error": str(exc)},
            )
            return

        self._last_fingerprint = fingerprint
        self._last_sent_at = sent_at
        _logger.info(
            "kitshop_sales_alert_sent",
            extra={"fingerprint": fingerprint},
        )


__all__ = ["TelegramKitShopSaleAlertNotifier"]
