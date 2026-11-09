from __future__ import annotations

from beartype import beartype


@beartype
def format_ops_force_notify(
    *,
    technician_display: str,
    machine_display: str,
    reason: str,
) -> str:
    return f"Технику {technician_display} поставлена задача: {machine_display}, причина {reason}"


@beartype
def format_dm_force_notify(*, machine_display: str) -> str:
    return f"Новая задача: {machine_display}"
