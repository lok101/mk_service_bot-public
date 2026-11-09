from __future__ import annotations

from datetime import UTC, datetime

from src.application.sales_monitoring.offline_lifecycle import (
    MachineOfflineInput,
    decide_offline_lifecycle,
)
from src.domain.ids import MachineId
from src.domain.sales_monitoring.event_ids import (
    offline_cleared_event_id,
    offline_opened_event_id,
)
from src.domain.sales_monitoring.events import (
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
)

_MACHINE_A = MachineId("m-a")
_NOW = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)


def test_offline_open_event_id_includes_opened_at() -> None:
    decision = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=True,
                open_opened_at=None,
            ),
        ),
        now=_NOW,
    )
    assert len(decision.opened) == 1
    opened = decision.opened[0]
    assert isinstance(opened, SalesMonitoringOfflineOpened)
    assert opened.opened_at == _NOW
    assert opened.event_id == offline_opened_event_id(
        machine_id=_MACHINE_A,
        opened_at=_NOW,
    )


def test_offline_reopen_after_clear_uses_new_cycle() -> None:
    first = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=True,
                open_opened_at=None,
            ),
        ),
        now=_OPENED_AT,
    )
    assert len(first.opened) == 1
    first_opened = first.opened[0]

    cleared = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=False,
                open_opened_at=first_opened.opened_at,
            ),
        ),
        now=_NOW,
    )
    assert len(cleared.cleared) == 1
    assert isinstance(cleared.cleared[0], SalesMonitoringOfflineCleared)
    assert cleared.cleared[0].opened_event_id == first_opened.event_id
    assert cleared.cleared[0].opened_at == first_opened.opened_at
    assert cleared.cleared[0].event_id == offline_cleared_event_id(
        machine_id=_MACHINE_A,
        cleared_at=_NOW,
    )

    reopen_at = datetime(2026, 7, 28, 11, 0, tzinfo=UTC)
    second = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=True,
                open_opened_at=None,
            ),
        ),
        now=reopen_at,
    )
    assert len(second.opened) == 1
    assert second.opened[0].opened_at == reopen_at
    assert second.opened[0].event_id != first_opened.event_id
    assert second.opened[0].event_id == offline_opened_event_id(
        machine_id=_MACHINE_A,
        opened_at=reopen_at,
    )


def test_unresolved_kit_id_skips_open() -> None:
    decision = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=None,
                is_offline=True,
                open_opened_at=None,
            ),
        ),
        now=_NOW,
    )
    assert decision.opened == ()
    assert decision.cleared == ()
    assert decision.unresolved_machine_ids == (_MACHINE_A,)


def test_unresolved_kit_id_skips_clear() -> None:
    decision = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=None,
                is_offline=False,
                open_opened_at=_OPENED_AT,
            ),
        ),
        now=_NOW,
    )
    assert decision.opened == ()
    assert decision.cleared == ()
    assert decision.unresolved_machine_ids == (_MACHINE_A,)


def test_online_without_open_is_noop() -> None:
    decision = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=False,
                open_opened_at=None,
            ),
        ),
        now=_NOW,
    )
    assert decision.opened == ()
    assert decision.cleared == ()
    assert decision.unresolved_machine_ids == ()


def test_offline_when_already_open_is_noop() -> None:
    decision = decide_offline_lifecycle(
        machines=(
            MachineOfflineInput(
                machine_id=_MACHINE_A,
                kit_id=101,
                is_offline=True,
                open_opened_at=_OPENED_AT,
            ),
        ),
        now=_NOW,
    )
    assert decision.opened == ()
    assert decision.cleared == ()
