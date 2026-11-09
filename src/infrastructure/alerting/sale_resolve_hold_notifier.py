from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation import HoldingSkipSample, ReasonClass
from src.infrastructure.alerting.telegram_log_handler import send_telegram_message

_logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@runtime_checkable
class SaleResolveHoldAlertNotifier(Protocol):
    @beartype
    def notify_holding(
        self,
        *,
        hold_at: datetime,
        holding_skip_count: int,
        fingerprint_pairs: Sequence[tuple[str, ReasonClass]],
        samples: Sequence[HoldingSkipSample],
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class NoOpSaleResolveHoldAlertNotifier:
    @beartype
    def notify_holding(
        self,
        *,
        hold_at: datetime,
        holding_skip_count: int,
        fingerprint_pairs: Sequence[tuple[str, ReasonClass]],
        samples: Sequence[HoldingSkipSample],
    ) -> None:
        del hold_at, holding_skip_count, fingerprint_pairs, samples


@beartype
@dataclass(slots=True)
class TelegramSaleResolveHoldAlertNotifier:
    bot_token: str
    chat_id: int
    cooldown_minutes: int
    now: Callable[[], datetime] = _utc_now
    _send: Callable[[str], None] | None = None
    _last_fingerprint: tuple[tuple[str, ReasonClass], ...] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_sent_at: datetime | None = field(default=None, init=False, repr=False)

    @beartype
    def notify_holding(
        self,
        *,
        hold_at: datetime,
        holding_skip_count: int,
        fingerprint_pairs: Sequence[tuple[str, ReasonClass]],
        samples: Sequence[HoldingSkipSample],
    ) -> None:
        fingerprint = tuple(fingerprint_pairs)
        sent_at = self.now()
        if (
            self._last_fingerprint == fingerprint
            and self._last_sent_at is not None
            and sent_at - self._last_sent_at < timedelta(minutes=self.cooldown_minutes)
        ):
            return

        sample_parts: list[str] = []
        for sample in samples:
            line = f"{sample.machine_key}/{sample.reason_class}@{sample.occurred_at.isoformat()}"
            if sample.detail != "":
                line = f"{line} {sample.detail}"
            sample_parts.append(line)
        sample_text = "; ".join(sample_parts) if sample_parts else "(none)"
        text = (
            f"Kit sales ingest holding skip: count={holding_skip_count} "
            f"hold_at={hold_at.isoformat()} cursor clamped. Sample: {sample_text}"
        )
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
                "sale_resolve_hold_alert_failed count=%s hold_at=%s error=%s",
                holding_skip_count,
                hold_at.isoformat(),
                exc,
            )
            return

        self._last_fingerprint = fingerprint
        self._last_sent_at = sent_at
