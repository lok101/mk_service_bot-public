from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO

import pytest

from src.application.sales_monitoring.status_board_errors import (
    StatusBoardMessageGoneError,
    StatusBoardNotModifiedError,
    StatusBoardTelegramError,
)
from src.infrastructure.sales_monitoring.telegram_notifiers import (
    TelegramSalesMonitoringReportNotifier,
    split_telegram_text,
    wrap_telegram_pre,
)

_STATUS_BOARD_OK_BODY = json.dumps({"ok": True, "result": {"message_id": 555}}).encode()


class _FakeTelegramOkResponse:
    status = 200

    def read(self) -> bytes:
        return _STATUS_BOARD_OK_BODY

    def __enter__(self) -> _FakeTelegramOkResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_split_telegram_text_keeps_short_message() -> None:
    assert split_telegram_text("hello") == ("hello",)


def test_split_telegram_text_splits_on_newlines() -> None:
    line = "x" * 100
    text = "\n".join([line] * 50)
    chunks = split_telegram_text(text, max_length=250)
    assert len(chunks) > 1
    assert all(len(chunk) <= 250 for chunk in chunks)
    assert "\n".join(chunks) == text


def test_split_telegram_text_hard_splits_when_no_newline() -> None:
    text = "a" * 100
    chunks = split_telegram_text(text, max_length=30)
    assert chunks == ("a" * 30, "a" * 30, "a" * 30, "a" * 10)
    assert "".join(chunks) == text


def test_send_report_sends_multiple_chunks() -> None:
    sent: list[str] = []
    notifier = TelegramSalesMonitoringReportNotifier(
        bot_token="token",
        chat_id=-100,
        _send=sent.append,
    )
    text = "\n".join(["line"] * 2000)
    notifier.send_report(text)
    assert len(sent) > 1
    assert all(chunk.startswith("<pre>") and chunk.endswith("</pre>") for chunk in sent)
    assert all(len(chunk) <= 4096 for chunk in sent)


def test_wrap_telegram_pre_escapes_html() -> None:
    assert wrap_telegram_pre("a <b> & c") == "<pre>a &lt;b&gt; &amp; c</pre>"


def test_post_telegram_includes_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeHTTPError(urllib.error.HTTPError):
        def read(self) -> bytes:  # type: ignore[override]
            return json.dumps(
                {"ok": False, "description": "Bad Request: chat not found"},
            ).encode()

    def _raise_http_error(
        request: object,
        timeout: float = 0,
    ) -> object:
        raise _FakeHTTPError(
            "https://api.telegram.org/bottoken/sendMessage",
            400,
            "Bad Request",
            None,  # type: ignore[arg-type]
            BytesIO(b""),
        )

    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.telegram_notifiers.urllib.request.urlopen",
        _raise_http_error,
    )
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="token", chat_id=1)

    with pytest.raises(urllib.error.HTTPError, match="chat not found"):
        notifier.send_report("hi")


def test_status_board_send_returns_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ok_urlopen(
        request: object,
        timeout: float = 0,
    ) -> _FakeTelegramOkResponse:
        return _FakeTelegramOkResponse()

    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.telegram_notifiers.urllib.request.urlopen",
        _ok_urlopen,
    )
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="token", chat_id=1)

    message_id = notifier.send_board("board text")

    assert message_id == 555


def test_status_board_edit_sends_html_pre(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[urllib.request.Request] = []

    def _capture_urlopen(
        request: urllib.request.Request,
        timeout: float = 0,
    ) -> _FakeTelegramOkResponse:
        captured.append(request)
        return _FakeTelegramOkResponse()

    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.telegram_notifiers.urllib.request.urlopen",
        _capture_urlopen,
    )
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="token", chat_id=1)

    notifier.edit_board(message_id=555, text="board text")

    assert len(captured) == 1
    request = captured[0]
    assert "editMessageText" in request.full_url
    assert request.data is not None
    payload = json.loads(request.data.decode())
    assert payload["message_id"] == 555
    assert payload["parse_mode"] == "HTML"
    assert payload["text"].startswith("<pre>")


def _urlopen_http_error(*, status: int, description: str):
    class _FakeHTTPError(urllib.error.HTTPError):
        def read(self) -> bytes:  # type: ignore[override]
            return json.dumps({"ok": False, "description": description}).encode()

    def _raise_http_error(
        request: object,
        timeout: float = 0,
    ) -> object:
        raise _FakeHTTPError(
            "https://api.telegram.org/bottoken/editMessageText",
            status,
            "Bad Request",
            None,  # type: ignore[arg-type]
            BytesIO(b""),
        )

    return _raise_http_error


def test_status_board_edit_gone_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.telegram_notifiers.urllib.request.urlopen",
        _urlopen_http_error(status=400, description="message to edit not found"),
    )
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="token", chat_id=1)

    with pytest.raises(StatusBoardMessageGoneError):
        notifier.edit_board(message_id=555, text="board text")


def test_status_board_edit_not_modified_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.telegram_notifiers.urllib.request.urlopen",
        _urlopen_http_error(status=400, description="message is not modified"),
    )
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="token", chat_id=1)

    with pytest.raises(StatusBoardNotModifiedError):
        notifier.edit_board(message_id=555, text="board text")


def test_status_board_send_maps_url_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_url(_request: object, timeout: float = 0) -> object:
        del timeout
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_url)
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="t", chat_id=1)
    with pytest.raises(StatusBoardTelegramError, match="network down"):
        notifier.send_board("hello")


def test_status_board_send_maps_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_timeout(_request: object, timeout: float = 0) -> object:
        del timeout
        raise TimeoutError("telegram timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    notifier = TelegramSalesMonitoringReportNotifier(bot_token="t", chat_id=1)
    with pytest.raises(StatusBoardTelegramError, match="telegram timeout"):
        notifier.send_board("hello")
