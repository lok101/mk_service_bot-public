from __future__ import annotations

from functools import reduce
from operator import or_
from typing import Literal

from aiogram.enums import ButtonStyle
from aiogram_dialog.widgets.style import Style
from beartype import beartype

from src.application.micromarket_loading.complete_maintenance_gate import (
    MICROMARKET_INVENTORY_REQUIRED_REASON,
)
from src.domain.results import ServiceCapabilities
from src.interfaces.telegram.machines.workspace_screen import button_label

CoffeeActivePhase = Literal["loading", "revision", "photos"] | None


@beartype
def awaiting_handover(caps: ServiceCapabilities) -> bool:
    return caps.responsibility_phase == "awaiting_handover"


@beartype
def coffee_active_phase(caps: ServiceCapabilities) -> CoffeeActivePhase:
    if not caps.loading_completed:
        return "loading"
    if awaiting_handover(caps):
        return "revision"
    if not caps.loading_photos_completed:
        return "photos"
    return None


@beartype
def coffee_phase_cue_prefixes(
    caps: ServiceCapabilities,
    *,
    revision_completed_today: bool = False,
) -> tuple[str, str, str]:
    """Return (loading, revision, photos) emoji prefixes for coffee workspace buttons."""
    loading_done = caps.loading_completed
    photos_done = caps.loading_photos_completed
    revision_flow = awaiting_handover(caps) or revision_completed_today

    loading_cue = "✅" if loading_done else "1️⃣"
    if awaiting_handover(caps):
        revision_cue = "2️⃣"
    elif revision_completed_today:
        revision_cue = "✅"
    else:
        revision_cue = "❎"

    if photos_done:
        photos_cue = "✅"
    elif revision_flow:
        photos_cue = "3️⃣"
    else:
        photos_cue = "2️⃣"

    return loading_cue, revision_cue, photos_cue


@beartype
def micromarket_phase_cue_prefixes(
    caps: ServiceCapabilities,
    *,
    checklist_step: int = 0,
) -> tuple[str, str, str, str, str]:
    """Return (c1, c2, c3, inventory, photos) emoji prefixes for MM workspace."""
    step = checklist_step if 0 <= checklist_step <= 3 else 0
    c1 = "✅" if step >= 1 else "1️⃣"
    c2 = "✅" if step >= 2 else "2️⃣"
    c3 = "✅" if step >= 3 else "3️⃣"
    inventory_pending = (
        caps.complete_maintenance_block_reason == MICROMARKET_INVENTORY_REQUIRED_REASON
    )
    inventory_cue = "4️⃣" if inventory_pending else "✅"
    photos_cue = "✅" if caps.loading_photos_completed else "5️⃣"
    return c1, c2, c3, inventory_cue, photos_cue


@beartype
def workspace_button_style_flags(
    caps: ServiceCapabilities,
    *,
    is_micromarket: bool = False,
    revision_completed_today: bool = False,
    checklist_step: int = 0,
) -> dict[str, bool]:
    """Boolean flags for Style(when=...) on workspace keyboard widgets."""
    if is_micromarket:
        step = checklist_step if 0 <= checklist_step <= 3 else 0
        return {
            "revision_style_success": caps.can_complete_revision,
            "loading_style_success": caps.can_submit_loading,
            "loading_style_danger": not caps.can_submit_loading,
            "complete_maintenance_style_success": False,
            "complete_maintenance_style_danger": not caps.can_complete_maintenance,
            "loading_photos_style_success": caps.can_submit_loading_photos,
            "loading_photos_style_danger": not caps.can_submit_loading_photos,
            "mm_checklist_1_style_success": step == 0,
            "mm_checklist_2_style_success": step == 1,
            "mm_checklist_3_style_success": step == 2,
        }
    active = coffee_active_phase(caps)
    return {
        "revision_style_success": active == "revision",
        "loading_style_success": active == "loading",
        "loading_style_danger": False,
        "complete_maintenance_style_success": False,
        "complete_maintenance_style_danger": False,
        "loading_photos_style_success": active == "photos",
        "loading_photos_style_danger": False,
        "mm_checklist_1_style_success": False,
        "mm_checklist_2_style_success": False,
        "mm_checklist_3_style_success": False,
    }


@beartype
def capability_prefix(*, available: bool) -> str:
    return "✅ " if available else "⛔ "


@beartype
def prefixed_button_label(action: str, *, available: bool) -> str:
    base = button_label(action)
    if action == "back":
        return base
    return capability_prefix(available=available) + base


@beartype
def workspace_action_button_texts(
    flags: dict[str, bool],
    *,
    snack_available: bool,
    snack_stub: bool,
    micromarket_available: bool,
    micromarket_stub: bool,
    complete_available: bool = False,
    is_micromarket: bool = False,
    caps: ServiceCapabilities | None = None,
    revision_completed_today: bool = False,
    checklist_step: int = 0,
) -> dict[str, str]:
    """Prefixed button labels for workspace getter payload keys."""
    if is_micromarket and caps is not None:
        c1, c2, c3, inventory_cue, photos_cue = micromarket_phase_cue_prefixes(
            caps,
            checklist_step=checklist_step,
        )
        return {
            "revision_button_text": prefixed_button_label(
                "revision",
                available=bool(flags.get("revision_style_success")),
            ),
            "loading_button_text": prefixed_button_label(
                "loading",
                available=bool(flags.get("loading_style_success")),
            ),
            "loading_photos_button_text": f"{photos_cue} {button_label('loading_photos')}",
            "complete_maintenance_button_text": button_label("complete_maintenance"),
            "snack_inventory_button_text": prefixed_button_label(
                "snack_inventory",
                available=snack_available and not snack_stub,
            ),
            "micromarket_inventory_button_text": (
                f"{inventory_cue} {button_label('micromarket_inventory')}"
            ),
            "mm_checklist_1_button_text": f"{c1} {button_label('mm_checklist_1')}",
            "mm_checklist_2_button_text": f"{c2} {button_label('mm_checklist_2')}",
            "mm_checklist_3_button_text": f"{c3} {button_label('mm_checklist_3')}",
        }

    _checklist_defaults = {
        "mm_checklist_1_button_text": button_label("mm_checklist_1"),
        "mm_checklist_2_button_text": button_label("mm_checklist_2"),
        "mm_checklist_3_button_text": button_label("mm_checklist_3"),
    }
    if caps is None:
        loading_available = bool(flags.get("loading_style_success"))
        photos_available = bool(flags.get("loading_photos_style_success"))
        danger = bool(flags.get("complete_maintenance_style_danger"))
        complete_ok = complete_available and not danger
        return {
            "revision_button_text": prefixed_button_label(
                "revision",
                available=bool(flags.get("revision_style_success")),
            ),
            "loading_button_text": prefixed_button_label(
                "loading",
                available=loading_available,
            ),
            "loading_photos_button_text": prefixed_button_label(
                "loading_photos",
                available=photos_available,
            ),
            "complete_maintenance_button_text": prefixed_button_label(
                "complete_maintenance",
                available=complete_ok,
            ),
            "snack_inventory_button_text": prefixed_button_label(
                "snack_inventory",
                available=snack_available and not snack_stub,
            ),
            "micromarket_inventory_button_text": prefixed_button_label(
                "micromarket_inventory",
                available=micromarket_available and not micromarket_stub,
            ),
            **_checklist_defaults,
        }

    loading_cue, revision_cue, photos_cue = coffee_phase_cue_prefixes(
        caps,
        revision_completed_today=revision_completed_today,
    )
    return {
        "revision_button_text": f"{revision_cue} {button_label('revision')}",
        "loading_button_text": f"{loading_cue} {button_label('loading')}",
        "loading_photos_button_text": f"{photos_cue} {button_label('loading_photos')}",
        "complete_maintenance_button_text": button_label("complete_maintenance"),
        "snack_inventory_button_text": prefixed_button_label(
            "snack_inventory",
            available=snack_available and not snack_stub,
        ),
        "micromarket_inventory_button_text": prefixed_button_label(
            "micromarket_inventory",
            available=micromarket_available and not micromarket_stub,
        ),
        **_checklist_defaults,
    }


def button_style_chain(*, success_when: str, danger_when: str | None = None) -> Style:
    parts: list[Style] = [Style(style=ButtonStyle.SUCCESS, when=success_when)]
    if danger_when is not None:
        parts.append(Style(style=ButtonStyle.DANGER, when=danger_when))
    parts.append(Style())
    return reduce(or_, parts)
