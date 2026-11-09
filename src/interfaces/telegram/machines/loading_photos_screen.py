from __future__ import annotations

from beartype import beartype

from src.application.photo_batches.loading_photos_limits import (
    resolve_loading_photos_cues,
)
from src.domain.results import loading_photos_excess_count_reason
from src.interfaces.telegram.dialog_layout import TELEGRAM_DIALOG_MIN_WIDTH_LINE

_COFFEE_CHECKLIST: tuple[str, ...] = (
    "1. Общий план ДО.",
    "2. Органайзер.",
    "3. Открытая машина.",
    "4. Открытый шкаф под машиной.",
    "5. Мусорное ведро, ведро жидких отходов, контейнер твердых отходов.",
    "6. Лоток и миксеры (разобранные и мытые).",
    "7. Сиропы.",
    "8. Работающий терминал.",
    "9. График визитов.",
    "10. Общий план ПОСЛЕ.",
)

PROFILE_MISSING_MESSAGE = "Для аппарата не настроен профиль фото. Обратитесь к координатору."


@beartype
def resolve_loading_photos_ui_limits(
    *,
    machine_code: str,
    coffee_min: int,
    coffee_max: int,
    kind_lookup: object | None,
    profile_lookup: object | None = None,
    profile_strict: bool = False,
) -> tuple[int, int, bool, tuple[str, ...], bool]:
    """Return (min, max, is_micromarket, checklist, profile_missing_strict)."""
    min_count, max_count, checklist, is_micromarket, profile_missing_strict = (
        resolve_loading_photos_cues(
            machine_code=machine_code,
            coffee_min=coffee_min,
            coffee_max=coffee_max,
            kind_lookup=kind_lookup,
            profile_lookup=profile_lookup,
            profile_strict=profile_strict,
            coffee_checklist=_COFFEE_CHECKLIST,
        )
    )
    return min_count, max_count, is_micromarket, checklist, profile_missing_strict


@beartype
def build_loading_photos_screen_text(
    *,
    photo_count: int,
    min_count: int,
    max_count: int,
    preview_index: int,
    checklist: tuple[str, ...] | None = None,
    is_micromarket: bool = False,
    profile_missing_strict: bool = False,
) -> str:
    if profile_missing_strict:
        return "\n".join(
            [
                TELEGRAM_DIALOG_MIN_WIDTH_LINE,
                "Загрузка фото",
                "",
                PROFILE_MISSING_MESSAGE,
            ]
        )
    items = checklist
    if items is None:
        items = (
            (
                "1. Общий план ДО.",
                "2. Общий план ПОСЛЕ.",
            )
            if is_micromarket
            else _COFFEE_CHECKLIST
        )
    lines = [
        TELEGRAM_DIALOG_MIN_WIDTH_LINE,
        "Загрузка фото",
        "",
        *items,
        "",
        f"Загружено: {photo_count} (мин. {min_count}, макс. {max_count})",
    ]
    if photo_count >= max_count:
        lines.append("Достигнут лимит фотографий.")
    if photo_count > 0:
        lines.append(f"Просмотр: фото {preview_index + 1} из {photo_count}")
    return "\n".join(lines)


@beartype
def insufficient_photos_alert(min_count: int) -> str:
    return f"Нужно минимум {min_count} фотографий."


@beartype
def max_photos_alert(max_count: int) -> str:
    return loading_photos_excess_count_reason(max_count)
