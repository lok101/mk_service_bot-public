from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from beartype import beartype

from src.application.machine_operations.ports import WarehouseInventoryFormUnconfigured
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.deps import MachineDialogDeps


@beartype
async def show_my_stock_inventory_form(message: Message, deps: MachineDialogDeps) -> None:
    if message.from_user is None:
        await message.answer("Не удалось определить склад техника.")
        return
    user = await resolve_bot_user(deps, message.from_user.id)
    if user is None or not user.is_active or user.technician_id is None:
        await message.answer("Не удалось определить склад техника.")
        return
    try:
        link = deps.technician_warehouse_inventory_link_provider.create_link(user.technician_id)
    except WarehouseInventoryFormUnconfigured:
        await message.answer("Форма инвентаризации склада не настроена.")
        return
    except ValueError as error:
        text = str(error).strip() or "Форма инвентаризации склада не настроена."
        await message.answer(text)
        return
    await message.answer(
        "Инвентаризация склада",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть форму", url=link.url)]],
        ),
    )
