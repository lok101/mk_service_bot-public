from __future__ import annotations

from typing import Literal

from beartype import beartype

from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_REQUIRE_LOADING_REASON,
    MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    REVISION_NOT_ALLOWED_REASON,
    ServiceCapabilities,
    maintenance_cooldown_reason,
)

ServiceAction = Literal[
    "revision",
    "loading",
    "complete_maintenance",
    "loading_photos",
]


@beartype
def blocked_service_action_reason(
    *,
    action: ServiceAction,
    caps: ServiceCapabilities | None,
    cooldown_active: bool | None,
    maintenance_cooldown_minutes: int,
    default_reason: str,
) -> str:
    if action == "revision":
        return REVISION_NOT_ALLOWED_REASON
    if action == "loading":
        return LOADING_NOT_ALLOWED_REASON
    if action == "complete_maintenance":
        if caps is not None and caps.maintenance_completed_today:
            return MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON
        gate_reason = caps.complete_maintenance_block_reason if caps is not None else None
        if gate_reason:
            return gate_reason
        inferred_cooldown = (
            caps is not None
            and caps.responsibility_phase == "responsible"
            and not caps.can_submit_loading_photos
            and not caps.maintenance_completed_today
        )
        if cooldown_active is True or (cooldown_active is None and inferred_cooldown):
            return maintenance_cooldown_reason(maintenance_cooldown_minutes)
        return MAINTENANCE_NOT_ALLOWED_REASON
    if caps is not None and caps.loading_photos_completed:
        return LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON
    photos_gate_reason = caps.loading_photos_block_reason if caps is not None else None
    if photos_gate_reason:
        return photos_gate_reason
    if caps is not None and not caps.loading_completed:
        return LOADING_PHOTOS_REQUIRE_LOADING_REASON
    inferred_cooldown = (
        caps is not None
        and caps.responsibility_phase == "responsible"
        and not caps.maintenance_completed_today
        and not caps.can_complete_maintenance
    )
    if cooldown_active is True or (cooldown_active is None and inferred_cooldown):
        return maintenance_cooldown_reason(maintenance_cooldown_minutes)
    return default_reason
