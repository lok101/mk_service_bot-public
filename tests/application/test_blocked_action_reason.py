from __future__ import annotations

import pytest

from src.application.machine_operations.blocked_action_reason import (
    ServiceAction,
    blocked_service_action_reason,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.results import (
    LOADING_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
    LOADING_PHOTOS_NOT_ALLOWED_REASON,
    LOADING_PHOTOS_REQUIRE_LOADING_REASON,
    MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
    MAINTENANCE_NOT_ALLOWED_REASON,
    REVISION_NOT_ALLOWED_REASON,
    ResponsibilityPhase,
    ServiceCapabilities,
    maintenance_cooldown_reason,
)


def _caps(
    *,
    can_complete_revision: bool = True,
    can_submit_loading: bool = True,
    can_submit_loading_photos: bool = True,
    can_complete_maintenance: bool = True,
    maintenance_completed_today: bool = False,
    loading_completed: bool = True,
    loading_photos_completed: bool = False,
    responsibility_phase: ResponsibilityPhase = "responsible",
    complete_maintenance_block_reason: str | None = None,
    loading_photos_block_reason: str | None = None,
) -> ServiceCapabilities:
    return ServiceCapabilities(
        technician_id=TechnicianId("tech-1"),
        machine_id=MachineId("vm-1"),
        responsibility_phase=responsibility_phase,
        can_complete_revision=can_complete_revision,
        can_submit_loading=can_submit_loading,
        can_submit_loading_photos=can_submit_loading_photos,
        can_complete_maintenance=can_complete_maintenance,
        revision_form_link=None,
        loading_completed=loading_completed,
        maintenance_completed_today=maintenance_completed_today,
        loading_photos_completed=loading_photos_completed,
        complete_maintenance_block_reason=complete_maintenance_block_reason,
        loading_photos_block_reason=loading_photos_block_reason,
    )


@pytest.mark.parametrize(
    ("action", "caps", "expected"),
    [
        ("revision", _caps(can_complete_revision=False), REVISION_NOT_ALLOWED_REASON),
        ("loading", _caps(can_submit_loading=False), LOADING_NOT_ALLOWED_REASON),
        (
            "complete_maintenance",
            _caps(can_complete_maintenance=False, maintenance_completed_today=True),
            MAINTENANCE_ALREADY_COMPLETED_TODAY_REASON,
        ),
        (
            "loading_photos",
            _caps(can_submit_loading_photos=False, loading_photos_completed=True),
            LOADING_PHOTOS_ALREADY_SUBMITTED_TODAY_REASON,
        ),
    ],
)
def test_blocked_service_action_reason_uses_capability_reason(
    action: ServiceAction,
    caps: ServiceCapabilities,
    expected: str,
) -> None:
    assert (
        blocked_service_action_reason(
            action=action,
            caps=caps,
            cooldown_active=None,
            maintenance_cooldown_minutes=60,
            default_reason="default",
        )
        == expected
    )


def test_blocked_service_action_reason_uses_cooldown_for_complete_maintenance() -> None:
    caps = _caps(
        can_complete_maintenance=False,
        can_submit_loading_photos=False,
        maintenance_completed_today=False,
        responsibility_phase="responsible",
    )

    assert blocked_service_action_reason(
        action="complete_maintenance",
        caps=caps,
        cooldown_active=None,
        maintenance_cooldown_minutes=60,
        default_reason=MAINTENANCE_NOT_ALLOWED_REASON,
    ) == maintenance_cooldown_reason(60)


def test_blocked_service_action_reason_uses_cooldown_for_loading_photos() -> None:
    caps = _caps(
        can_submit_loading_photos=False,
        can_complete_maintenance=False,
        maintenance_completed_today=False,
        loading_completed=True,
        loading_photos_completed=False,
        responsibility_phase="responsible",
    )

    assert blocked_service_action_reason(
        action="loading_photos",
        caps=caps,
        cooldown_active=None,
        maintenance_cooldown_minutes=60,
        default_reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
    ) == maintenance_cooldown_reason(60)


def test_blocked_service_action_reason_requires_loading_for_photos() -> None:
    caps = _caps(
        can_submit_loading_photos=False,
        loading_completed=False,
        loading_photos_completed=False,
        responsibility_phase="responsible",
    )

    assert (
        blocked_service_action_reason(
            action="loading_photos",
            caps=caps,
            cooldown_active=None,
            maintenance_cooldown_minutes=60,
            default_reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
        )
        == LOADING_PHOTOS_REQUIRE_LOADING_REASON
    )


def test_blocked_service_action_reason_accepts_explicit_cooldown_for_service_result() -> None:
    assert blocked_service_action_reason(
        action="complete_maintenance",
        caps=None,
        cooldown_active=True,
        maintenance_cooldown_minutes=60,
        default_reason=MAINTENANCE_NOT_ALLOWED_REASON,
    ) == maintenance_cooldown_reason(60)


def test_blocked_service_action_reason_falls_back_to_default() -> None:
    caps = _caps(
        can_submit_loading_photos=False,
        can_complete_maintenance=True,
        maintenance_completed_today=True,
        loading_photos_completed=False,
        responsibility_phase="responsible",
    )

    assert (
        blocked_service_action_reason(
            action="loading_photos",
            caps=caps,
            cooldown_active=None,
            maintenance_cooldown_minutes=60,
            default_reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
        )
        == LOADING_PHOTOS_NOT_ALLOWED_REASON
    )


def test_blocked_service_action_reason_falls_back_to_maintenance_not_allowed() -> None:
    caps = _caps(
        can_complete_maintenance=False,
        can_submit_loading_photos=True,
        maintenance_completed_today=False,
        responsibility_phase="responsible",
    )

    assert (
        blocked_service_action_reason(
            action="complete_maintenance",
            caps=caps,
            cooldown_active=None,
            maintenance_cooldown_minutes=60,
            default_reason="unused-default",
        )
        == MAINTENANCE_NOT_ALLOWED_REASON
    )


def test_blocked_service_action_reason_prefers_complete_block_reason() -> None:
    caps = _caps(
        can_complete_maintenance=False,
        complete_maintenance_block_reason="нужна инвентаризация холодильника",
    )
    assert (
        blocked_service_action_reason(
            action="complete_maintenance",
            caps=caps,
            cooldown_active=False,
            maintenance_cooldown_minutes=30,
            default_reason=MAINTENANCE_NOT_ALLOWED_REASON,
        )
        == "нужна инвентаризация холодильника"
    )


def test_blocked_service_action_reason_prefers_photos_block_reason() -> None:
    caps = _caps(
        can_submit_loading_photos=False,
        loading_photos_block_reason="сначала пересчёт загрузки",
    )
    assert (
        blocked_service_action_reason(
            action="loading_photos",
            caps=caps,
            cooldown_active=False,
            maintenance_cooldown_minutes=30,
            default_reason=LOADING_PHOTOS_NOT_ALLOWED_REASON,
        )
        == "сначала пересчёт загрузки"
    )
