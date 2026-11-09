from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from beartype import beartype

from src.application.machine_operations import GetServiceCapabilitiesCommand
from src.application.photo_batches import PhotoBatchRejectedError
from src.interfaces.telegram.machines.bot_user import resolve_bot_user
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.handlers_common import (
    HANDLERS_BEARTYPE_CONF,
    CommonHandlersMixin,
)
from src.interfaces.telegram.machines.loading_photos_dialog_data import (
    clear_loading_photos_session,
    get_loading_photos_batch_id,
    get_photo_index,
    init_loading_photos_session,
    photo_count,
    photos_as_refs,
    set_photo_index,
    try_append_photo,
)
from src.interfaces.telegram.machines.loading_photos_screen import (
    insufficient_photos_alert,
    max_photos_alert,
    resolve_loading_photos_ui_limits,
)
from src.interfaces.telegram.machines.state import MachineListState
from src.interfaces.telegram.machines.workspace_screen import stub_reason_for_action


@beartype(conf=HANDLERS_BEARTYPE_CONF)
class LoadingPhotosHandlersMixin(CommonHandlersMixin):
    def _loading_photos_ui_limits(self, manager: DialogManager) -> tuple[int, int]:
        machine_id = get_selected_machine_id(manager)
        min_count, max_count, _mm, _checklist, missing = resolve_loading_photos_ui_limits(
            machine_code=machine_id.value,
            coffee_min=self.deps.loading_photos_min_count,
            coffee_max=self.deps.loading_photos_max_count,
            kind_lookup=self.deps.machine_kind_lookup,
            profile_lookup=getattr(self.deps, "loading_photos_profile_lookup", None),
            profile_strict=bool(getattr(self.deps, "visit_photo_profile_strict", False)),
        )
        if missing:
            return 0, 0
        return min_count, max_count

    async def on_loading_photos_click(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        if not caps.can_submit_loading_photos:
            await self._answer_if_action_blocked(
                callback,
                bot_user=bot_user,
                machine_id=machine_id,
                can_flag=False,
                domain_reason=stub_reason_for_action("loading_photos"),
                action="loading_photos",
            )
            return

        init_loading_photos_session(manager)
        await callback.answer()
        await manager.switch_to(MachineListState.loading_photos)

    async def on_loading_photos_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return
        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        await self._answer_if_action_blocked(
            callback,
            bot_user=bot_user,
            machine_id=machine_id,
            can_flag=caps.can_submit_loading_photos,
            domain_reason=stub_reason_for_action("loading_photos"),
            action="loading_photos",
        )

    async def on_loading_photos_photo_received(
        self,
        message: Message,
        widget: MessageInput,
        manager: DialogManager,
    ) -> None:
        if message.photo is None or not message.photo:
            return
        _min_count, max_count = self._loading_photos_ui_limits(manager)
        photo = message.photo[-1]
        if not try_append_photo(
            manager,
            max_count=max_count,
            file_id=photo.file_id,
            file_unique_id=photo.file_unique_id,
            message_id=message.message_id,
            media_group_id=message.media_group_id,
        ):
            await message.answer(max_photos_alert(max_count))

    async def on_loading_photos_prev(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        count = photo_count(manager)
        if count <= 1:
            await callback.answer()
            return
        index = get_photo_index(manager)
        set_photo_index(manager, (index - 1) % count)
        await callback.answer()

    async def on_loading_photos_next(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        count = photo_count(manager)
        if count <= 1:
            await callback.answer()
            return
        index = get_photo_index(manager)
        set_photo_index(manager, (index + 1) % count)
        await callback.answer()

    async def on_loading_photos_back(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        clear_loading_photos_session(manager)
        await callback.answer()
        await manager.switch_to(MachineListState.workspace)

    async def on_loading_photos_send_stub(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        count = photo_count(manager)
        min_count, max_count = self._loading_photos_ui_limits(manager)
        if count > max_count:
            await callback.answer(
                max_photos_alert(max_count),
                show_alert=True,
            )
            return
        await callback.answer(
            insufficient_photos_alert(min_count),
            show_alert=True,
        )

    async def on_loading_photos_send(
        self,
        callback: CallbackQuery,
        button: Button,
        manager: DialogManager,
    ) -> None:
        bot_user = await resolve_bot_user(self.deps, callback.from_user.id)
        machine_id = get_selected_machine_id(manager)
        technician_id = await self._require_technician_id(
            callback,
            bot_user,
            machine_id,
        )
        if technician_id is None:
            return

        min_count, max_count = self._loading_photos_ui_limits(manager)
        count = photo_count(manager)
        if count > max_count:
            await callback.answer(
                max_photos_alert(max_count),
                show_alert=True,
            )
            return
        if count < min_count:
            await callback.answer(
                insufficient_photos_alert(min_count),
                show_alert=True,
            )
            return

        caps = self.deps.get_service_capabilities.execute(
            GetServiceCapabilitiesCommand(
                technician_id=technician_id,
                machine_id=machine_id,
            ),
        )
        if not caps.can_submit_loading_photos:
            await self._answer_if_action_blocked(
                callback,
                bot_user=bot_user,
                machine_id=machine_id,
                can_flag=False,
                domain_reason=stub_reason_for_action("loading_photos"),
                action="loading_photos",
            )
            return

        photos = photos_as_refs(manager)
        if len(photos) < min_count:
            await callback.answer(
                insufficient_photos_alert(min_count),
                show_alert=True,
            )
            return

        try:
            self.deps.accept_loading_photos.execute(
                batch_id=get_loading_photos_batch_id(manager),
                technician_id=technician_id,
                machine_id=machine_id,
                submitted_at=datetime.now(tz=UTC),
                photos=photos,
            )
        except PhotoBatchRejectedError as error:
            await callback.answer(error.reason, show_alert=True)
            return

        clear_loading_photos_session(manager)
        await callback.answer("Фото отправлены.")
        await manager.switch_to(MachineListState.workspace)
