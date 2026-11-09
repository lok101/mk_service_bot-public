from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.application.sales_monitoring.status_board_errors import StatusBoardTelegramError
from src.infrastructure.composition.wiring.wire_sales_monitoring_worker import (
    _safe_publish_status_board,
)


class _BoomPublish:
    def execute(self, **kwargs: object) -> None:
        del kwargs
        raise StatusBoardTelegramError("telegram down")


class _SlowPublish:
    def __init__(self) -> None:
        self.concurrent = 0
        self.max_concurrent = 0
        self._guard = threading.Lock()

    def execute(self, **kwargs: object) -> None:
        del kwargs
        with self._guard:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        time.sleep(0.05)
        with self._guard:
            self.concurrent -= 1


class _RecordingPublish:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def execute(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def test_no_sales_stale_callback_swallows_publish_error() -> None:
    _safe_publish_status_board(
        _BoomPublish(),
        mode="sync",
        catalog=(),
        now=datetime(2026, 8, 25, 8, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        timezone=ZoneInfo("Europe/Moscow"),
        stale_hours=24,
        last_sale_lookup_days=28,
        operational_timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        excluded_codes=frozenset(),
    )


def test_status_board_publish_lock_serializes_concurrent_calls() -> None:
    publish = _SlowPublish()
    kwargs = dict(
        mode="sync",
        catalog=(),
        now=datetime(2026, 8, 25, 8, 0, tzinfo=ZoneInfo("Europe/Moscow")),
        timezone=ZoneInfo("Europe/Moscow"),
        stale_hours=24,
        last_sale_lookup_days=28,
        operational_timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        excluded_codes=frozenset(),
    )
    threads = [
        threading.Thread(target=_safe_publish_status_board, args=(publish,), kwargs=kwargs)
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert publish.max_concurrent == 1


def test_status_board_publish_passes_operational_calendar() -> None:
    """happy: wiring helper прокидывает operational_timezone и day_end_hour."""
    publish = _RecordingPublish()
    ops_tz = ZoneInfo("Europe/Moscow")
    _safe_publish_status_board(
        publish,
        mode="sync",
        catalog=(),
        now=datetime(2026, 8, 26, 8, 0, tzinfo=ops_tz),
        timezone=ops_tz,
        stale_hours=24,
        last_sale_lookup_days=28,
        operational_timezone=ops_tz,
        day_end_hour=12,
        excluded_codes=frozenset({"138"}),
    )
    assert publish.kwargs is not None
    assert publish.kwargs["operational_timezone"] == ops_tz
    assert publish.kwargs["day_end_hour"] == 12
    assert "cleared_ttl_hours" not in publish.kwargs
    assert publish.kwargs["excluded_codes"] == frozenset({"138"})
