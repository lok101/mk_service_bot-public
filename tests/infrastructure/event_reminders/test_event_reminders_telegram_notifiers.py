from __future__ import annotations

import json

import pytest

from src.infrastructure.event_reminders.telegram_notifiers import (
    HttpAlertNotifier,
    HttpReminderNotifier,
    wrap_telegram_pre,
)


def test_wrap_telegram_pre_escapes_html() -> None:
    assert "&lt;" in wrap_telegram_pre("<x>")
    assert wrap_telegram_pre("a <b> & c") == "<pre>a &lt;b&gt; &amp; c</pre>"


def test_telegram_sends_html_pre(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        reason = "OK"
        headers: dict[str, str] = {}

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        captured["url"] = getattr(request, "full_url", None)
        data = getattr(request, "data", b"")
        assert isinstance(data, bytes)
        captured["payload"] = json.loads(data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(
        "src.infrastructure.event_reminders.telegram_notifiers.urllib.request.urlopen",
        fake_urlopen,
    )
    notifier = HttpReminderNotifier(bot_token="t", chat_id=1)
    notifier.send_plain_pre_content("hello &")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["parse_mode"] == "HTML"
    assert payload["chat_id"] == 1
    text = payload["text"]
    assert isinstance(text, str)
    assert text.startswith("<pre>")
    assert text.endswith("</pre>")
    assert "hello &amp;" in text
    assert "<pre>" in text


def test_alert_notifier_sends_plain_without_parse_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _Response:
        status = 200
        reason = "OK"
        headers: dict[str, str] = {}

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> _Response:
        data = getattr(request, "data", b"")
        assert isinstance(data, bytes)
        captured["payload"] = json.loads(data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(
        "src.infrastructure.event_reminders.telegram_notifiers.urllib.request.urlopen",
        fake_urlopen,
    )
    notifier = HttpAlertNotifier(bot_token="alert-t", chat_id=-100)
    notifier.send_text("event_reminders: bad row → Foo <bar> & baz")

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == -100
    assert payload["text"] == "event_reminders: bad row → Foo <bar> & baz"
    assert "parse_mode" not in payload
