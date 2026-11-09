from __future__ import annotations

from src.application.service_visits import format_dm_force_notify, format_ops_force_notify


def test_format_ops_force_notify_text() -> None:
    """happy: ops строка."""
    assert (
        format_ops_force_notify(
            technician_display="Иван",
            machine_display="Аппарат 101",
            reason="no_sales",
        )
        == "Технику Иван поставлена задача: Аппарат 101, причина no_sales"
    )


def test_format_dm_force_notify_text() -> None:
    """happy: DM строка."""
    assert format_dm_force_notify(machine_display="Аппарат 101") == "Новая задача: Аппарат 101"
