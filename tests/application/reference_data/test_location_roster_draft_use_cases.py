from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.reference_data import (
    LocationRosterConflict,
    LocationRosterEntry,
    LocationRosterInvalid,
    LocationRosterPatch,
)
from src.application.reference_data.location_roster_draft import (
    ApplyLocationRosterDraft,
    BootstrapLocationRosterDraft,
    ResetLocationRosterDraft,
    UpsertLocationRosterDraft,
)
from src.application.reference_data.location_roster_draft_memory import (
    InMemoryLocationRosterDraftStore,
)
from src.application.reference_data.location_roster_memory import InMemoryLocationRosterStore
from src.domain.ids import MachineId, TechnicianId

_NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
_M1 = MachineId("101")
_M2 = MachineId("102")
_TECH = TechnicianId("001")


def _entry(
    machine: MachineId,
    *,
    tech: TechnicianId | None = _TECH,
    days: frozenset[int] = frozenset({1}),
    at: datetime = _NOW,
) -> LocationRosterEntry:
    return LocationRosterEntry(
        machine_id=machine,
        technician_id=tech,
        service_weekdays=days,
        updated_at=at,
        updated_by_telegram_user_id=42,
    )


def test_bootstrap_copies_applied_when_draft_empty() -> None:
    applied = InMemoryLocationRosterStore()
    applied.replace_all((_entry(_M1),))
    draft = InMemoryLocationRosterDraftStore()
    BootstrapLocationRosterDraft(applied=applied, draft=draft).execute(
        catalog_machine_ids=frozenset({_M1}),
        now=_NOW,
        actor_telegram_user_id=0,
    )
    loaded = draft.get(_M1)
    assert loaded is not None
    assert loaded.technician_id == _TECH
    assert loaded.service_weekdays == frozenset({1})


def test_bootstrap_fills_only_missing_machine_ids() -> None:
    applied = InMemoryLocationRosterStore()
    applied.replace_all((_entry(_M1, days=frozenset({0})), _entry(_M2, days=frozenset({2}))))
    draft = InMemoryLocationRosterDraftStore()
    existing = _entry(_M1, days=frozenset({6}), at=_NOW)
    draft.upsert(existing, expected_updated_at=None)
    BootstrapLocationRosterDraft(applied=applied, draft=draft).execute(
        catalog_machine_ids=frozenset({_M1, _M2}),
        now=_NOW,
        actor_telegram_user_id=0,
    )
    assert draft.get(_M1) is not None
    assert draft.get(_M1).service_weekdays == frozenset({6})  # type: ignore[union-attr]
    assert draft.get(_M2) is not None
    assert draft.get(_M2).service_weekdays == frozenset({2})  # type: ignore[union-attr]


def test_upsert_draft_rejects_unknown_machine() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    uc = UpsertLocationRosterDraft(draft=draft)
    with pytest.raises(LocationRosterInvalid):
        uc.execute(
            LocationRosterPatch(
                machine_id=_M1,
                technician_id=_TECH,
                service_weekdays=frozenset({1}),
            ),
            expected_updated_at=None,
            catalog_machine_ids=frozenset(),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1,
            now=_NOW,
        )
    assert applied.is_empty()


def test_upsert_draft_stale_expected_raises_conflict() -> None:
    draft = InMemoryLocationRosterDraftStore()
    draft.upsert(_entry(_M1), expected_updated_at=None)
    uc = UpsertLocationRosterDraft(draft=draft)
    with pytest.raises(LocationRosterConflict):
        uc.execute(
            LocationRosterPatch(
                machine_id=_M1,
                technician_id=_TECH,
                service_weekdays=frozenset({2}),
            ),
            expected_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            catalog_machine_ids=frozenset({_M1}),
            directory_technician_ids=frozenset({_TECH}),
            actor_telegram_user_id=1,
            now=_NOW,
        )


def test_upsert_draft_does_not_touch_applied_store() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    applied.replace_all((_entry(_M1, days=frozenset({0})),))
    UpsertLocationRosterDraft(draft=draft).execute(
        LocationRosterPatch(
            machine_id=_M1,
            technician_id=_TECH,
            service_weekdays=frozenset({3}),
        ),
        expected_updated_at=None,
        catalog_machine_ids=frozenset({_M1}),
        directory_technician_ids=frozenset({_TECH}),
        actor_telegram_user_id=1,
        now=_NOW,
    )
    assert applied.get(_M1) is not None
    assert applied.get(_M1).service_weekdays == frozenset({0})  # type: ignore[union-attr]
    assert draft.get(_M1) is not None
    assert draft.get(_M1).service_weekdays == frozenset({3})  # type: ignore[union-attr]


def test_apply_draft_writes_applied_and_invokes_refresh() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    draft.upsert(_entry(_M1, days=frozenset({4})), expected_updated_at=None)
    refresh_calls: list[tuple[LocationRosterEntry, ...]] = []

    def _refresh(entries: tuple[LocationRosterEntry, ...]) -> None:
        refresh_calls.append(entries)

    result = ApplyLocationRosterDraft(
        draft=draft,
        applied=applied,
        on_applied=_refresh,
    ).execute(
        catalog_machine_ids=frozenset({_M1}),
        directory_technician_ids=frozenset({_TECH}),
        expected_draft_updated_at={_M1: _NOW},
        expected_applied_updated_at={},
        actor_telegram_user_id=7,
        now=_NOW,
    )
    assert result.applied is True
    assert applied.get(_M1) is not None
    assert applied.get(_M1).service_weekdays == frozenset({4})  # type: ignore[union-attr]
    assert len(refresh_calls) == 1


def test_apply_when_clean_is_noop_without_refresh() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    entry = _entry(_M1)
    applied.replace_all((entry,))
    draft.upsert(entry, expected_updated_at=None)
    calls: list[object] = []

    result = ApplyLocationRosterDraft(
        draft=draft,
        applied=applied,
        on_applied=lambda _e: calls.append(1),
    ).execute(
        catalog_machine_ids=frozenset({_M1}),
        directory_technician_ids=frozenset({_TECH}),
        expected_draft_updated_at={_M1: _NOW},
        expected_applied_updated_at={_M1: _NOW},
        actor_telegram_user_id=7,
        now=_NOW,
    )
    assert result.applied is False
    assert calls == []


def test_apply_stale_draft_version_raises_conflict() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    draft.upsert(_entry(_M1), expected_updated_at=None)
    with pytest.raises(LocationRosterConflict):
        ApplyLocationRosterDraft(
            draft=draft,
            applied=applied,
            on_applied=lambda _e: None,
        ).execute(
            catalog_machine_ids=frozenset({_M1}),
            directory_technician_ids=frozenset({_TECH}),
            expected_draft_updated_at={_M1: datetime(2020, 1, 1, tzinfo=UTC)},
            expected_applied_updated_at={},
            actor_telegram_user_id=7,
            now=_NOW,
        )


def test_reset_draft_copies_applied() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    applied.replace_all((_entry(_M1, days=frozenset({0})),))
    draft.upsert(_entry(_M1, days=frozenset({5})), expected_updated_at=None)
    ResetLocationRosterDraft(draft=draft, applied=applied).execute(
        catalog_machine_ids=frozenset({_M1}),
        expected_draft_updated_at={_M1: _NOW},
        now=_NOW,
        actor_telegram_user_id=3,
    )
    assert draft.get(_M1) is not None
    assert draft.get(_M1).service_weekdays == frozenset({0})  # type: ignore[union-attr]


def test_reset_stale_token_raises_conflict() -> None:
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    draft.upsert(_entry(_M1), expected_updated_at=None)
    with pytest.raises(LocationRosterConflict):
        ResetLocationRosterDraft(draft=draft, applied=applied).execute(
            catalog_machine_ids=frozenset({_M1}),
            expected_draft_updated_at={_M1: datetime(2019, 1, 1, tzinfo=UTC)},
            now=_NOW,
            actor_telegram_user_id=3,
        )


def test_reset_accepts_sub_millisecond_token_skew() -> None:
    """happy: BSON Date = ms; client token with extra µs must not 409 (LOK-112)."""
    draft = InMemoryLocationRosterDraftStore()
    applied = InMemoryLocationRosterStore()
    applied.replace_all((_entry(_M1, days=frozenset({0})),))
    stored_at = datetime(2026, 8, 26, 12, 0, 0, 123000, tzinfo=UTC)
    client_token = datetime(2026, 8, 26, 12, 0, 0, 123456, tzinfo=UTC)
    draft.upsert(_entry(_M1, days=frozenset({5}), at=stored_at), expected_updated_at=None)
    ResetLocationRosterDraft(draft=draft, applied=applied).execute(
        catalog_machine_ids=frozenset({_M1}),
        expected_draft_updated_at={_M1: client_token},
        now=_NOW,
        actor_telegram_user_id=3,
    )
    assert draft.get(_M1) is not None
    assert draft.get(_M1).service_weekdays == frozenset({0})  # type: ignore[union-attr]
