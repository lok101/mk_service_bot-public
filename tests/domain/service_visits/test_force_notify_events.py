from __future__ import annotations

from src.domain.service_visits import visit_force_notify_event_id


def test_visit_force_notify_event_id_format() -> None:
    """happy: стабильный ключ цикла."""
    assert (
        visit_force_notify_event_id("extra:101", "2026-08-12T08:00:00+00:00")
        == "visit_force_notify:extra:101:2026-08-12T08:00:00+00:00"
    )
