from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from beartype import beartype

JOURNAL_CAPACITY = 100

# Prior RUNNING row closed when a newer publish journal entry is enqueued (ISS-009).
SUPERSEDED_BY_NEWER_PUBLISH_RU = "заменена новой публикацией"


class ShopListPublishJournalStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def label_ru(self) -> str:
        match self:
            case ShopListPublishJournalStatus.RUNNING:
                return "в процессе"
            case ShopListPublishJournalStatus.SUCCEEDED:
                return "успешно"
            case ShopListPublishJournalStatus.FAILED:
                return "ошибка"


class ShopListPublishTrigger(StrEnum):
    """Источник команды на витрину (человек или система).

    ``inventory_restore`` — контракт для LOK-314: соседний путь обязан
    передавать этот trigger и заполнять ``enabled_product_codes`` без
    rename полей журнала.
    """

    MANUAL = "manual"
    INVENTORY_ZERO = "inventory_zero"
    INVENTORY_RESTORE = "inventory_restore"
    PENDING_EXIT = "pending_exit"
    LOADING_SHELF = "loading_shelf"
    POST_VISIT_SQUEEZE = "post_visit_squeeze"

    @property
    def label_ru(self) -> str:
        match self:
            case ShopListPublishTrigger.MANUAL:
                return "Опубликовать"
            case ShopListPublishTrigger.INVENTORY_ZERO:
                return "система · нуль"
            case ShopListPublishTrigger.INVENTORY_RESTORE:
                return "система · восстановление"
            case ShopListPublishTrigger.PENDING_EXIT:
                return "система · выбытие"
            case ShopListPublishTrigger.LOADING_SHELF:
                return "система · полка загрузки"
            case ShopListPublishTrigger.POST_VISIT_SQUEEZE:
                return "система · пост-визитный дожим"


LEGACY_TRIGGER_LABEL_RU = "публикация"


@beartype
def shop_list_publish_trigger_label(trigger: ShopListPublishTrigger | None) -> str:
    if trigger is None:
        return LEGACY_TRIGGER_LABEL_RU
    return trigger.label_ru


@beartype
@dataclass(frozen=True, slots=True)
class ShopListPublishEffects:
    disabled_product_codes: tuple[str, ...] = ()
    enabled_product_codes: tuple[str, ...] = ()
    added_product_codes: tuple[str, ...] = ()
    removed_product_codes: tuple[str, ...] = ()
    updated_product_codes: tuple[str, ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class ShopListIntendedLine:
    product_code: str
    price_rub: Decimal
    kit_group_id: int
    availability_off: bool


@beartype
def shop_list_publish_effects_summary(effects: ShopListPublishEffects) -> str:
    """Компактная сводка: ``снято N · возвращено M · +A −R ~U`` (нули опускать)."""
    parts: list[str] = []
    if effects.disabled_product_codes:
        parts.append(f"снято {len(effects.disabled_product_codes)}")
    if effects.enabled_product_codes:
        parts.append(f"возвращено {len(effects.enabled_product_codes)}")
    structural: list[str] = []
    if effects.added_product_codes:
        structural.append(f"+{len(effects.added_product_codes)}")
    if effects.removed_product_codes:
        structural.append(f"−{len(effects.removed_product_codes)}")
    if effects.updated_product_codes:
        structural.append(f"~{len(effects.updated_product_codes)}")
    if structural:
        parts.append(" ".join(structural))
    return " · ".join(parts)


@beartype
def _product_display_label(code: str, catalog_names: Mapping[str, str] | None) -> str:
    if catalog_names is None:
        return code
    name = catalog_names.get(code, "").strip()
    return name if name else code


@beartype
def _updated_change_note(
    code: str,
    *,
    intended_by_code: Mapping[str, ShopListIntendedLine],
    baseline_by_code: Mapping[str, ShopListIntendedLine],
    disabled_codes: frozenset[str],
    enabled_codes: frozenset[str],
) -> str:
    intended = intended_by_code.get(code)
    previous = baseline_by_code.get(code)
    if intended is not None and previous is not None:
        parts: list[str] = []
        if previous.price_rub != intended.price_rub:
            parts.append(f"цена {previous.price_rub}→{intended.price_rub} ₽")
        if previous.availability_off != intended.availability_off:
            parts.append(
                "доступность: снят" if intended.availability_off else "доступность: возвращён"
            )
        if previous.kit_group_id != intended.kit_group_id:
            parts.append(f"группа {previous.kit_group_id}→{intended.kit_group_id}")
        return ", ".join(parts) if parts else "поля витрины"
    if code in disabled_codes:
        return "доступность: снят"
    if code in enabled_codes:
        return "доступность: возвращён"
    return "поля витрины"


@beartype
def shop_list_publish_effects_detail_lines(
    effects: ShopListPublishEffects,
    catalog_names: Mapping[str, str] | None = None,
    *,
    intended_lines: Sequence[ShopListIntendedLine] = (),
    baseline_lines: Sequence[ShopListIntendedLine] | None = None,
) -> tuple[str, ...]:
    """Строки деталей: одна на SKU, имена из catalog_names (ISS-401)."""
    intended_by_code = {line.product_code: line for line in intended_lines}
    baseline_by_code = (
        {line.product_code: line for line in baseline_lines} if baseline_lines is not None else {}
    )
    disabled_codes = frozenset(effects.disabled_product_codes)
    enabled_codes = frozenset(effects.enabled_product_codes)
    lines: list[str] = []
    buckets: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("снято", effects.disabled_product_codes),
        ("возвращено", effects.enabled_product_codes),
        ("добавлено", effects.added_product_codes),
        ("убрано", effects.removed_product_codes),
        ("изменено", effects.updated_product_codes),
    )
    for label, codes in buckets:
        for code in codes:
            display = _product_display_label(code, catalog_names)
            if label == "изменено":
                note = _updated_change_note(
                    code,
                    intended_by_code=intended_by_code,
                    baseline_by_code=baseline_by_code,
                    disabled_codes=disabled_codes,
                    enabled_codes=enabled_codes,
                )
                lines.append(f"{label}: {display} — {note}")
            else:
                lines.append(f"{label}: {display}")
    return tuple(lines)


@beartype
@dataclass(frozen=True, slots=True)
class ShopListLastSucceededSnapshot:
    machine_code: str
    lines: tuple[ShopListIntendedLine, ...]
    updated_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class ShopListPublishJournalEntry:
    publication_id: str
    machine_code: str
    status: ShopListPublishJournalStatus
    created_at: datetime
    updated_at: datetime
    error_message: str = ""
    trigger: ShopListPublishTrigger | None = None
    effects: ShopListPublishEffects = field(default_factory=ShopListPublishEffects)
    intended_lines: tuple[ShopListIntendedLine, ...] = ()
    baseline_lines: tuple[ShopListIntendedLine, ...] = ()


@beartype
def diff_shop_list_intended(
    baseline: tuple[ShopListIntendedLine, ...] | None,
    intended: tuple[ShopListIntendedLine, ...],
) -> ShopListPublishEffects:
    """Pure diff intended snapshot vs last-succeeded baseline → journal effects.

    До merge LOK-314 exclude (factual zero) → ``availability_off`` →
    ``disabled_product_codes``. Код может одновременно попасть в
    ``updated_*`` и availability-bucket.
    """
    intended_by_code = {line.product_code: line for line in intended}
    if baseline is None:
        first_added = tuple(sorted(intended_by_code))
        first_disabled = tuple(
            sorted(code for code, line in intended_by_code.items() if line.availability_off)
        )
        return ShopListPublishEffects(
            disabled_product_codes=first_disabled,
            added_product_codes=first_added,
        )

    baseline_by_code = {line.product_code: line for line in baseline}
    added: list[str] = []
    removed: list[str] = []
    updated: list[str] = []
    disabled: list[str] = []
    enabled: list[str] = []

    for code, line in intended_by_code.items():
        previous = baseline_by_code.get(code)
        if previous is None:
            added.append(code)
            if line.availability_off:
                disabled.append(code)
            continue
        fields_changed = (
            previous.price_rub != line.price_rub
            or previous.kit_group_id != line.kit_group_id
            or previous.availability_off != line.availability_off
        )
        if fields_changed:
            updated.append(code)
        if not previous.availability_off and line.availability_off:
            disabled.append(code)
        elif previous.availability_off and not line.availability_off:
            enabled.append(code)

    for code in baseline_by_code:
        if code not in intended_by_code:
            removed.append(code)

    return ShopListPublishEffects(
        disabled_product_codes=tuple(sorted(disabled)),
        enabled_product_codes=tuple(sorted(enabled)),
        added_product_codes=tuple(sorted(added)),
        removed_product_codes=tuple(sorted(removed)),
        updated_product_codes=tuple(sorted(updated)),
    )
