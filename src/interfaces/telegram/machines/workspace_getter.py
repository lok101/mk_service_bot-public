from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from aiogram_dialog import DialogManager
from beartype import beartype

from src.application.machine_operations import GetServiceCapabilitiesCommand
from src.application.master_data import MachineKind
from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
)
from src.application.micromarket_loading.issue_inventory_link import IssueMicromarketInventoryLink
from src.application.snack_loading.issue_inventory_link import IssueSnackInventoryLink
from src.application.snack_loading.ports import SnackInventoryCellsSource
from src.domain.calendar import operational_day
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import ServiceCapabilities
from src.domain.system_user import SystemUser
from src.interfaces.telegram.machines.access import (
    can_use_bot,
    technician_id_for_machine_operations,
)
from src.interfaces.telegram.machines.bot_user import (
    bot_user_ui_fields,
    get_event_user,
    resolve_bot_user,
)
from src.interfaces.telegram.machines.deps import MachineListDeps
from src.interfaces.telegram.machines.dialog_data import get_selected_machine_id
from src.interfaces.telegram.machines.form_workflow_error import read_form_workflow_error
from src.interfaces.telegram.machines.maintenance_screen import (
    last_loading_line_for_machine,
    last_service_line_for_machine,
    maintenance_screen_flags,
)
from src.interfaces.telegram.machines.micromarket_field_checklist import (
    get_checklist_step,
    inventory_unlocked_by_checklist,
    sync_checklist_machine,
)
from src.interfaces.telegram.machines.micromarket_inventory_workspace import (
    issue_micromarket_inventory_now_link,
    micromarket_inventory_workspace_flags,
    resolve_micromarket_inventory_form_pages,
)
from src.interfaces.telegram.machines.snack_inventory_workspace import (
    snack_inventory_workspace_flags,
)
from src.interfaces.telegram.machines.workspace_links import (
    _LOADING_URL_KEY,
    _MICROMARKET_INVENTORY_ISSUE_ERROR_KEY,
    _MICROMARKET_INVENTORY_URL_KEY,
    _REVISION_URL_KEY,
)
from src.interfaces.telegram.machines.workspace_screen import build_workspace_screen_text
from src.interfaces.telegram.machines.workspace_styles import (
    workspace_action_button_texts,
    workspace_button_style_flags,
)

DialogDataGetter = Callable[..., Awaitable[dict[str, object]]]


@beartype
def _non_empty_url(dialog_data: dict[str, object], key: str) -> bool:
    value = dialog_data.get(key)
    return isinstance(value, str) and bool(value.strip())


@beartype
def _workspace_user_fields(bot_user: SystemUser | None) -> dict[str, object]:
    return {
        key: value
        for key, value in bot_user_ui_fields(bot_user).items()
        if key != "user_profile_line"
    }


def build_workspace_payload(
    deps: MachineListDeps,
    *,
    dialog_manager: DialogManager,
    bot_user: SystemUser | None,
    machine_id: MachineId,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    machine_id_value = machine_id.value
    machine_name = dialog_manager.dialog_data.get("machine_name")
    if not isinstance(machine_name, str) or not machine_name:
        machine_name = machine_id_value

    if bot_user is None or not can_use_bot(bot_user):
        inactive_flags = _inactive_style_flags(machine_id)
        return {
            **_workspace_user_fields(bot_user),
            "workspace_screen_text": "Не удалось загрузить данные аппарата.",
            "revision_has_url": False,
            "loading_has_url": False,
            "loading_photos_onboarding_stub": False,
            "loading_photos_responsible_stub": False,
            "can_submit_loading_photos": False,
            "loading_photos_completed": False,
            "can_complete_maintenance": False,
            "show_maintenance_back": False,
            "snack_inventory_available": False,
            "snack_inventory_show_stub": False,
            "micromarket_inventory_available": False,
            "micromarket_inventory_show_stub": False,
            "micromarket_inventory_clickable": False,
            "micromarket_inventory_has_url": False,
            "micromarket_inventory_checklist_locked": False,
            "show_mm_field_checklist": False,
            "show_coffee_revision": True,
            "show_coffee_loading": True,
            "show_snack_inventory": True,
            **inactive_flags,
            **_blocked_action_button_texts(inactive_flags),
        }

    technician_id = technician_id_for_machine_operations(bot_user)
    if technician_id is None:
        inactive_flags = _inactive_style_flags(machine_id)
        return {
            **_workspace_user_fields(bot_user),
            "workspace_screen_text": "Операции с аппаратом недоступны для этой учётной записи.",
            "revision_has_url": False,
            "loading_has_url": False,
            "loading_photos_onboarding_stub": False,
            "loading_photos_responsible_stub": False,
            "can_submit_loading_photos": False,
            "loading_photos_completed": False,
            "can_complete_maintenance": False,
            "show_maintenance_back": False,
            "micromarket_inventory_clickable": False,
            "micromarket_inventory_has_url": False,
            "micromarket_inventory_checklist_locked": False,
            "show_mm_field_checklist": False,
            "snack_inventory_available": False,
            "snack_inventory_show_stub": False,
            "micromarket_inventory_available": False,
            "micromarket_inventory_show_stub": False,
            "show_coffee_revision": True,
            "show_coffee_loading": True,
            "show_snack_inventory": True,
            **inactive_flags,
            **_blocked_action_button_texts(inactive_flags),
        }

    caps = deps.get_service_capabilities.execute(
        GetServiceCapabilitiesCommand(
            technician_id=technician_id,
            machine_id=machine_id,
        ),
    )
    flags = maintenance_screen_flags(deps, bot_user=bot_user, machine_id=machine_id)
    dialog_data = dialog_manager.dialog_data
    form_error = read_form_workflow_error(dialog_data)
    screen_checked_at = checked_at if checked_at is not None else datetime.now(tz=UTC)

    snack_issuer = deps.issue_snack_inventory_link
    snack_cells = deps.snack_inventory_cells
    if snack_issuer is not None and not isinstance(snack_issuer, IssueSnackInventoryLink):
        snack_issuer = None
    if snack_cells is not None and not isinstance(snack_cells, SnackInventoryCellsSource):
        snack_cells = None

    kind = None
    if deps.machine_kind_lookup is not None:
        kind = deps.machine_kind_lookup.kind_of(machine_id_value)
    is_micromarket = kind is MachineKind.MICRO_MARKET
    mm_issuer = deps.issue_micromarket_inventory_link
    if mm_issuer is not None and not isinstance(mm_issuer, IssueMicromarketInventoryLink):
        mm_issuer = None
    micromarket_flags = micromarket_inventory_workspace_flags(
        is_micromarket=is_micromarket,
        issuer=mm_issuer,
    )
    if is_micromarket:
        sync_checklist_machine(dialog_data, machine_id=machine_id_value)
    checklist_step = get_checklist_step(dialog_data) if is_micromarket else 0
    inventory_already_done = (
        caps.complete_maintenance_block_reason != MICROMARKET_INVENTORY_REQUIRED_REASON
    )
    inventory_unlocked = inventory_unlocked_by_checklist(
        checklist_step=checklist_step,
        inventory_already_done=inventory_already_done,
    )
    mm_available = bool(micromarket_flags["micromarket_inventory_available"])
    mm_config_stub = bool(micromarket_flags["micromarket_inventory_show_stub"])
    micromarket_inventory_clickable = mm_available and inventory_unlocked
    micromarket_inventory_checklist_locked = mm_available and not inventory_unlocked
    micromarket_inventory_has_url = _provision_micromarket_inventory_url(
        deps,
        dialog_data,
        machine_id_value=machine_id_value,
        technician_id=technician_id,
        clickable=micromarket_inventory_clickable,
        issuer=mm_issuer,
    )

    snack_flags = snack_inventory_workspace_flags(
        machine_code=machine_id_value,
        cells_source=snack_cells,
        issuer=snack_issuer,
    )
    if not micromarket_flags["show_snack_inventory"]:
        snack_flags = {
            "snack_inventory_available": False,
            "snack_inventory_show_stub": False,
        }
    revision_completed_today = False
    if not is_micromarket:
        revision_completed_today = _revision_completed_on_ops_day(
            deps,
            machine_id=machine_id,
            technician_id=technician_id,
            checked_at=screen_checked_at,
        )
    style_flags = workspace_button_style_flags(
        caps,
        is_micromarket=is_micromarket,
        revision_completed_today=revision_completed_today,
        checklist_step=checklist_step,
    )
    loading_photos_onboarding_stub = (
        caps.responsibility_phase == "awaiting_handover" and not is_micromarket
    )
    return {
        **_workspace_user_fields(bot_user),
        "workspace_screen_text": build_workspace_screen_text(
            caps=caps,
            machine_name=machine_name,
            machine_id=machine_id_value,
            last_loading_line=last_loading_line_for_machine(deps, machine_id),
            last_service_line=last_service_line_for_machine(deps, machine_id),
            form_error=form_error,
            service_timezone=deps.service_display_timezone,
            checked_at=screen_checked_at,
            is_micromarket=is_micromarket,
        ),
        "revision_has_url": caps.can_complete_revision
        and _non_empty_url(dialog_data, _REVISION_URL_KEY),
        "loading_has_url": caps.can_submit_loading
        and _non_empty_url(dialog_data, _LOADING_URL_KEY),
        "loading_photos_onboarding_stub": loading_photos_onboarding_stub,
        "loading_photos_responsible_stub": (
            not caps.can_submit_loading_photos and not loading_photos_onboarding_stub
        ),
        "can_submit_loading_photos": caps.can_submit_loading_photos,
        "loading_photos_completed": caps.loading_photos_completed,
        "can_complete_maintenance": caps.can_complete_maintenance,
        "show_maintenance_back": flags.show_maintenance_back,
        "show_mm_field_checklist": is_micromarket,
        "micromarket_inventory_clickable": micromarket_inventory_clickable,
        "micromarket_inventory_has_url": micromarket_inventory_has_url,
        "micromarket_inventory_checklist_locked": micromarket_inventory_checklist_locked,
        **snack_flags,
        **micromarket_flags,
        **style_flags,
        **workspace_action_button_texts(
            style_flags,
            snack_available=bool(snack_flags["snack_inventory_available"]),
            snack_stub=bool(snack_flags["snack_inventory_show_stub"]),
            micromarket_available=mm_available,
            micromarket_stub=mm_config_stub,
            complete_available=caps.can_complete_maintenance,
            is_micromarket=is_micromarket,
            caps=caps,
            revision_completed_today=revision_completed_today,
            checklist_step=checklist_step,
        ),
    }


def _revision_completed_on_ops_day(
    deps: MachineListDeps,
    *,
    machine_id: MachineId,
    technician_id: TechnicianId,
    checked_at: datetime,
) -> bool:
    # Not @beartype: dialog tests pass MagicMock deps (same as build_workspace_payload).
    aggregate = deps.machine_operations.get(machine_id)
    # Accessors are methods (settlement blockers / domain public surface).
    opened_at = aggregate.last_revision_opened_at()
    opened_by = aggregate.last_revision_opened_by()

    if opened_at is None or opened_by != technician_id:
        return False
    if not isinstance(opened_at, datetime):
        return False
    timezone = deps.service_display_timezone
    end_hour = deps.service_day_end_hour
    return operational_day(opened_at, timezone, end_hour) == operational_day(
        checked_at,
        timezone,
        end_hour,
    )


@beartype
def _inactive_style_flags(machine_id: MachineId) -> dict[str, bool]:
    placeholder = ServiceCapabilities(
        technician_id=TechnicianId("0"),
        machine_id=machine_id,
        responsibility_phase="awaiting_handover",
        can_complete_revision=False,
        can_submit_loading=False,
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        revision_form_link=None,
    )
    return workspace_button_style_flags(placeholder)


_ISSUE_FAILED_ALERT = "Не удалось выдать форму инвентаризации."


def _provision_micromarket_inventory_url(
    deps: MachineListDeps,
    dialog_data: dict[str, object],
    *,
    machine_id_value: str,
    technician_id: TechnicianId,
    clickable: bool,
    issuer: IssueMicromarketInventoryLink | None,
) -> bool:
    """Issue inventory link into dialog_data for Url button (ISS-017). Sync getter."""
    if not clickable or issuer is None:
        dialog_data.pop(_MICROMARKET_INVENTORY_URL_KEY, None)
        dialog_data.pop(_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY, None)
        return False
    planogram_store = deps.micromarket_planogram_store
    stock_store = deps.micromarket_stock_store
    if planogram_store is None or stock_store is None:
        dialog_data.pop(_MICROMARKET_INVENTORY_URL_KEY, None)
        dialog_data.pop(_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY, None)
        return False
    try:
        pages = resolve_micromarket_inventory_form_pages(
            machine_code=machine_id_value,
            planogram_store=planogram_store,
            stock_store=stock_store,
            products=deps.domain_product_store,
        )
        result = issue_micromarket_inventory_now_link(
            machine_code=machine_id_value,
            technician_id=technician_id,
            issuer=issuer,
            pages=pages,
        )
    except Exception:
        dialog_data.pop(_MICROMARKET_INVENTORY_URL_KEY, None)
        dialog_data[_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY] = _ISSUE_FAILED_ALERT
        return False
    if isinstance(result, str):
        dialog_data.pop(_MICROMARKET_INVENTORY_URL_KEY, None)
        dialog_data[_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY] = result
        return False
    dialog_data[_MICROMARKET_INVENTORY_URL_KEY] = result.form_url
    dialog_data.pop(_MICROMARKET_INVENTORY_ISSUE_ERROR_KEY, None)
    return True


@beartype
def _blocked_action_button_texts(flags: dict[str, bool]) -> dict[str, str]:
    return workspace_action_button_texts(
        flags,
        snack_available=False,
        snack_stub=True,
        micromarket_available=False,
        micromarket_stub=True,
        complete_available=False,
        is_micromarket=True,
    )


def build_workspace_getter(deps: MachineListDeps) -> DialogDataGetter:
    async def get_workspace(
        dialog_manager: DialogManager,
        **kwargs: object,
    ) -> dict[str, object]:
        event_user = get_event_user(kwargs)
        bot_user = None
        if event_user is not None:
            bot_user = await resolve_bot_user(deps, event_user.id)

        machine_id = get_selected_machine_id(dialog_manager)
        return build_workspace_payload(
            deps,
            dialog_manager=dialog_manager,
            bot_user=bot_user,
            machine_id=machine_id,
        )

    return get_workspace
