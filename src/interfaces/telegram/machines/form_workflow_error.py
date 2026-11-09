from __future__ import annotations

from beartype import beartype


@beartype
def format_form_error_block(detail: str) -> str:
    trimmed = detail.strip()
    if not trimmed:
        return "🔴 ОШИБКА 🔴\n\nНе удалось принять форму."

    return f"🔴 ОШИБКА 🔴\n\n{trimmed}"


@beartype
def read_form_workflow_error(dialog_data: dict[str, object]) -> str | None:
    value = dialog_data.get("form_workflow_error")
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed
