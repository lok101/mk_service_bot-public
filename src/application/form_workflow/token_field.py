from __future__ import annotations

from beartype import beartype

from src.domain.form_submission import FormAnswer

_DEFAULT_FIELD_NAME = "Код заявки."


@beartype
def normalize_form_field_title(title: str) -> str:
    return title.strip()


@beartype
def find_form_token_in_answers(
    answers: tuple[FormAnswer, ...],
    field_name: str,
) -> str | None:
    normalized_field = normalize_form_field_title(field_name)
    for answer in answers:
        if normalize_form_field_title(answer.title) != normalized_field:
            continue
        value = answer.value.strip()
        return value if value else None
    return None


@beartype
def _display_field_name(field_name: str) -> str:
    trimmed = field_name.strip()
    return trimmed if trimmed else _DEFAULT_FIELD_NAME


@beartype
def _edit_hint(field_name: str) -> str:
    field = _display_field_name(field_name)
    return f"Не изменяйте и не удаляйте символы в поле «{field}» — откройте форму заново из бота."


@beartype
def form_token_answer_mismatch_message(field_name: str) -> str:
    field = _display_field_name(field_name)
    return f"Значение в поле «{field}» не совпадает с кодом заявки. {_edit_hint(field_name)}"


@beartype
def format_form_token_field_error(
    technical_detail: str,
    field_name: str,
) -> str:
    """Map domain token verification errors to a technician-facing Russian message."""
    detail = technical_detail.strip()
    field = _display_field_name(field_name)
    hint = _edit_hint(field_name)

    if not detail:
        return f"Не удалось принять код в поле «{field}». {hint}"

    lowered = detail.lower()

    if "must not be empty" in lowered:
        return f"Поле «{field}» пустое. {hint}"

    if "has invalid format" in lowered:
        return f"Поле «{field}» заполнено неверно — код повреждён или обрезан. {hint}"

    if "signature is invalid" in lowered:
        return f"Код в поле «{field}» не принят — возможно, его изменили вручную. {hint}"

    if "has expired" in lowered:
        return f"Код в поле «{field}» устарел. Откройте форму снова из бота."

    if "purpose is invalid" in lowered or "purpose is missing" in lowered:
        return f"Код в поле «{field}» не подходит для этой формы. {hint}"

    if "secret must not be empty" in lowered:
        return detail

    return f"Не удалось принять код в поле «{field}». {hint}"
