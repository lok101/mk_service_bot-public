from __future__ import annotations

from src.application.machine_operations.ports import EventStore


def test_event_store_protocol_exposes_maintenance_completed_window_query() -> None:
    assert hasattr(EventStore, "list_maintenance_completed_in_completed_at_window")
