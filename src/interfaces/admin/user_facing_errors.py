from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

_FALLBACK_CAUSE = "Не удалось выполнить действие."
_FALLBACK_ACTION = "Если неясно, что исправить — напишите в поддержку и приложите код ниже."


@dataclass(frozen=True, slots=True)
class AdminUserFacingError:
    code: str
    cause: str
    action: str
    targets: tuple[str, ...] = ()


_LOADING_CATALOG: dict[str, tuple[str, str]] = {
    "qty_above_available": (
        "Количество по позициям больше доступного на складе с учётом брони.",
        "Уменьшите qty по отмеченным SKU до доступного остатка и сохраните снова.",
    ),
    "order_recounted": (
        "Ордер загрузки уже пересчитан — повторный запуск из сборки сейчас нельзя.",
        "Дождитесь следующего цикла или закройте текущий ордер по процессу.",
    ),
    "order_not_found": (
        "Ордер сборки не найден.",
        "Обновите страницу и выберите ордер из списка открытых.",
    ),
    "order_not_open": (
        "Ордер сборки уже не в статусе «открыт».",
        "Создайте новый ордер или выберите другой открытый.",
    ),
    "empty_session": (
        "Нет открытых ордеров сборки для загрузки.",
        "Сначала создайте ордер сборки с количеством больше нуля.",
    ),
    "lines_empty": (
        "В ордере нет позиций с количеством больше нуля.",
        "Укажите qty хотя бы по одному SKU.",
    ),
    "warehouse_snapshot_missing": (
        "Нет снимка остатков главного склада.",
        "Повторите позже; если не поможет — напишите в поддержку с кодом ниже.",
    ),
    "order_closed_same_day": (
        "В этот операционный день ордер загрузки уже закрывали.",
        "Новый запуск возможен на следующий операционный день.",
    ),
    "launch_qty_above_warehouse": (
        "Сумма к загрузке больше доступного на складе.",
        "Уменьшите qty в ордерах сборки и повторите запуск.",
    ),
    "no_catalog_positions": (
        "Нечего загружать: нет позиций каталога с положительным qty.",
        "Проверьте ордера сборки и черновик загрузки.",
    ),
    "all_launch_qty_zero": (
        "Все количества к запуску равны нулю.",
        "Задайте launch qty больше нуля или исправьте ордера сборки.",
    ),
    "ops_accept_rejected": (
        "Подтверждение загрузки без пересчёта отклонено.",
        "Проверьте, что есть открытый ордер и у вас есть право ops-accept.",
    ),
    "no_order": (
        "Нет открытого ордера загрузки для подтверждения.",
        "Сначала запустите загрузку или дождитесь ордера.",
    ),
    "missing_order_id": (
        "У цикла загрузки нет id ордера.",
        "Обновите страницу; если повторится — напишите в поддержку с кодом ниже.",
    ),
    "assembly_order_rejected": (
        "Операция с ордером сборки отклонена.",
        "Проверьте статус ордера и количества; при необходимости напишите с кодом ниже.",
    ),
    "загрузка выключена": (
        "Загрузка микромаркета выключена настройкой.",
        "Включите execute/gate или обратитесь к тому, кто управляет выключателем.",
    ),
}


@beartype
def admin_error_present(
    code: str,
    *,
    targets: tuple[str, ...] = (),
) -> AdminUserFacingError:
    normalized = code.strip()
    stable_targets = tuple(sorted({item.strip() for item in targets if item.strip()}))
    catalog_key = normalized
    if normalized.startswith("duplicate_catalog_code:"):
        catalog_key = "duplicate_catalog_code"
        dup = normalized.split(":", 1)[1].strip()
        if dup and dup not in stable_targets:
            stable_targets = tuple(sorted({*stable_targets, dup}))
    if normalized.startswith("order_status_"):
        catalog_key = "order_status"
    if normalized.startswith("warehouse_read_failed:") or normalized.startswith("move_failed:"):
        catalog_key = "integration_failed"
    if normalized.startswith("launch_qty_above_warehouse"):
        catalog_key = "launch_qty_above_warehouse"

    entry = _LOADING_CATALOG.get(catalog_key)
    if catalog_key == "duplicate_catalog_code":
        cause = "Этот SKU уже есть в другом открытом ордере сборки этого аппарата."
        action = "Уберите дубликат или отмените прежний ордер."
        if stable_targets:
            listed = ", ".join(stable_targets)
            cause = f"{cause} Коды: {listed}."
        return AdminUserFacingError(
            code=normalized,
            cause=cause,
            action=action,
            targets=stable_targets,
        )
    if catalog_key == "order_status":
        return AdminUserFacingError(
            code=normalized,
            cause="Ордер загрузки в статусе, где это действие нельзя.",
            action="Обновите страницу и действуйте по текущему статусу ордера.",
            targets=stable_targets,
        )
    if catalog_key == "integration_failed":
        return AdminUserFacingError(
            code=normalized,
            cause="Сбой при обращении к складу или перемещению.",
            action="Повторите позже; если не поможет — напишите в поддержку с кодом ниже.",
            targets=stable_targets,
        )
    if entry is None:
        return AdminUserFacingError(
            code=normalized or "unknown",
            cause=_FALLBACK_CAUSE,
            action=_FALLBACK_ACTION,
            targets=stable_targets,
        )
    cause, action = entry
    if catalog_key == "qty_above_available" and stable_targets:
        listed = ", ".join(stable_targets)
        cause = f"{cause} SKU: {listed}."
    return AdminUserFacingError(
        code=normalized,
        cause=cause,
        action=action,
        targets=stable_targets,
    )
