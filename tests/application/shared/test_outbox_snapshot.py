from __future__ import annotations

import pytest

from src.application.shared.outbox_snapshot import snapshot_for_event


class _NotFound(Exception):
    pass


def test_returns_primary_when_present() -> None:
    result = snapshot_for_event(
        event_id="evt-1",
        primary_lookup=lambda event_id: f"primary:{event_id}",
        fallback_lookup=lambda: "fallback",
        not_found_error=lambda event_id: _NotFound(event_id),
    )
    assert result == "primary:evt-1"


def test_falls_back_when_primary_missing() -> None:
    result = snapshot_for_event(
        event_id="evt-2",
        primary_lookup=lambda event_id: None,
        fallback_lookup=lambda: "fallback",
        not_found_error=lambda event_id: _NotFound(event_id),
    )
    assert result == "fallback"


def test_raises_passed_error_when_both_missing() -> None:
    with pytest.raises(_NotFound, match="evt-3"):
        snapshot_for_event(
            event_id="evt-3",
            primary_lookup=lambda event_id: None,
            fallback_lookup=lambda: None,
            not_found_error=lambda event_id: _NotFound(event_id),
        )
