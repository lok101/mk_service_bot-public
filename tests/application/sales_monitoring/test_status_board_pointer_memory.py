from __future__ import annotations

from datetime import UTC, datetime

from src.application.sales_monitoring.status_board_pointer import StatusBoardPointer
from src.infrastructure.sales_monitoring.memory_status_board import (
    InMemoryStatusBoardPointerStore,
)


def test_status_board_pointer_roundtrip() -> None:
    """happy: save затем load тот же singleton."""
    store = InMemoryStatusBoardPointerStore()
    assert store.load() is None
    pointer = StatusBoardPointer(
        chat_id=-100,
        message_id=42,
        posted_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
        last_text="hello",
    )
    store.save(pointer)
    loaded = store.load()
    assert loaded == pointer
    store.save(
        StatusBoardPointer(
            chat_id=-100,
            message_id=99,
            posted_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
            last_text="next",
        )
    )
    assert store.load() is not None
    assert store.load().message_id == 99
