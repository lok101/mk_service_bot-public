from __future__ import annotations

from datetime import UTC, datetime

from src.application.inventory_reconciliation.kitvending import HoldingSkipSample
from src.infrastructure.alerting.sale_resolve_hold_notifier import (
    TelegramSaleResolveHoldAlertNotifier,
)


def test_resolve_hold_alert_dedup_and_fingerprint_change() -> None:
    sent: list[str] = []
    notifier = TelegramSaleResolveHoldAlertNotifier(
        bot_token="t",
        chat_id=1,
        cooldown_minutes=60,
        now=lambda: datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        _send=sent.append,
    )
    pairs = (("176", "critical_product_resolve"),)
    notifier.notify_holding(
        hold_at=datetime(2026, 8, 3, 10, 0, tzinfo=UTC),
        holding_skip_count=1,
        fingerprint_pairs=pairs,
        samples=(),
    )
    assert len(sent) == 1
    assert "holding" in sent[0].lower() or "Hold" in sent[0]
    hold_at = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    notifier.notify_holding(
        hold_at=hold_at,
        holding_skip_count=1,
        fingerprint_pairs=pairs,
        samples=(),
    )
    assert len(sent) == 1  # cooldown same fingerprint
    notifier.notify_holding(
        hold_at=hold_at,
        holding_skip_count=2,
        fingerprint_pairs=(("176", "critical_product_resolve"), ("200", "no_machine_code")),
        samples=(),
    )
    assert len(sent) == 2  # fingerprint changed


def test_holding_sample_includes_russian_domain_product_text() -> None:
    sent: list[str] = []
    occurred_at = datetime(2026, 5, 2, 7, 0, tzinfo=UTC)
    detail = "На карточке код доменного номера, а товара с таким номером нет."
    notifier = TelegramSaleResolveHoldAlertNotifier(
        bot_token="t",
        chat_id=1,
        cooldown_minutes=60,
        now=lambda: datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        _send=sent.append,
    )
    notifier.notify_holding(
        hold_at=occurred_at,
        holding_skip_count=2,
        fingerprint_pairs=(
            ("176", "critical_product_resolve"),
            ("kit_vm:1", "no_machine_code"),
        ),
        samples=(
            HoldingSkipSample(
                occurred_at=occurred_at,
                reason_class="critical_product_resolve",
                machine_key="176",
                detail=detail,
            ),
            HoldingSkipSample(
                occurred_at=occurred_at,
                reason_class="no_machine_code",
                machine_key="kit_vm:1",
            ),
        ),
    )
    assert len(sent) == 1
    text = sent[0]
    prefix = f"176/critical_product_resolve@{occurred_at.isoformat()}"
    assert prefix in text
    assert f"{prefix} {detail}" in text
    empty = f"kit_vm:1/no_machine_code@{occurred_at.isoformat()}"
    assert empty in text
    assert f"{empty} " not in text
