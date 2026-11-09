from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.alerting.kitshop_sale_alert_notifier import (
    TelegramKitShopSaleAlertNotifier,
)


def _notifier(
    sent: list[str],
    clock: list[datetime],
) -> TelegramKitShopSaleAlertNotifier:
    return TelegramKitShopSaleAlertNotifier(
        bot_token="token",
        chat_id=-100,
        cooldown_minutes=60,
        now=lambda: clock[0],
        _send=sent.append,
    )


def test_kitshop_alert_cooldown_suppresses_same_fingerprint() -> None:
    # happy: тот же набор причин внутри 60 минут не шлётся снова
    sent: list[str] = []
    clock = [datetime(2026, 9, 22, 12, 0, tzinfo=UTC)]
    notifier = _notifier(sent, clock)
    notifier.notify_held(count=1, reasons=("company_miss",))
    clock[0] = clock[0] + timedelta(minutes=59)
    notifier.notify_held(count=4, reasons=("company_miss",))
    assert sent == ["Kit Shop sales: 1 held (company_miss)."]


def test_kitshop_alert_different_fingerprint_sends_immediately() -> None:
    # edge: другой набор причин не ждёт cooldown
    sent: list[str] = []
    clock = [datetime(2026, 9, 22, 12, 0, tzinfo=UTC)]
    notifier = _notifier(sent, clock)
    notifier.notify_held(count=1, reasons=("company_miss",))
    notifier.notify_held(count=1, reasons=("shop_miss",))
    assert sent == [
        "Kit Shop sales: 1 held (company_miss).",
        "Kit Shop sales: 1 held (shop_miss).",
    ]


def test_kitshop_alert_phase_failed_text() -> None:
    # happy
    sent: list[str] = []
    clock = [datetime(2026, 9, 22, 12, 0, tzinfo=UTC)]
    notifier = _notifier(sent, clock)
    notifier.notify_phase_failed(phase="discovery", exception_type="KitShopNetworkError")
    assert sent == ["Kit Shop sales: discovery failed (KitShopNetworkError)."]


def test_kitshop_alert_send_failure_does_not_raise() -> None:
    # error: сбой отправки не валит вызывающего
    def _boom(text: str) -> None:
        del text
        raise RuntimeError("telegram down")

    notifier = TelegramKitShopSaleAlertNotifier(
        bot_token="token",
        chat_id=-100,
        cooldown_minutes=60,
        _send=_boom,
    )
    notifier.notify_held(count=1, reasons=("company_miss",))


@pytest.mark.parametrize(
    ("reason", "phrase"),
    [
        (
            "domain_product_unlinked",
            "Товар не связан с карточкой каталога, продажа не записана.",
        ),
        (
            "domain_product_link_broken",
            "Связь с карточкой каталога порвана, продажа не записана.",
        ),
        (
            "domain_product_catalog_archived",
            "Карточка каталога в архиве, продажа не записана.",
        ),
        (
            "unknown_domain_number",
            "На карточке код доменного номера, а товара с таким номером нет.",
        ),
    ],
)
def test_kitshop_hold_alert_uses_russian_domain_product_text(reason: str, phrase: str) -> None:
    sent: list[str] = []
    clock = [datetime(2026, 9, 23, 12, 0, tzinfo=UTC)]
    notifier = _notifier(sent, clock)
    notifier.notify_held(count=1, reasons=(reason, "company_miss"))
    assert sent == [f"Kit Shop sales: 1 held (company_miss, {phrase})."]
    assert notifier._last_fingerprint == ("held", "company_miss", reason)
