from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.application.visit_photo_review.fakes import (
    FixedBatches,
    FixedCatalog,
    FixedClock,
    MemoryGroupAvatarWriter,
    MemoryLearnedReferenceWriter,
    MemoryReviewStore,
)

from src.application.visit_photo_review.commands import (
    AppendLearnedReference,
    AppendLearnedReferenceError,
    AssignBatchGroups,
    ClearReviewRecord,
    RecordFrameView,
    RecordMissingRequiredGroup,
    RelocateBatchIndex,
    SaveReviewRecord,
    UpdateGroupDefects,
    UpdateGroupDefectsError,
    WriteGroupAvatar,
    WriteGroupAvatarError,
)
from src.application.visit_photo_review.ports import (
    AcceptedBatch,
    AcceptedPhotoFile,
    CatalogUnavailable,
)
from src.domain.visit_photo_review import (
    AssignError,
    CatalogGroup,
    DefectButton,
    DefectMark,
    FrameView,
    GroupAssignment,
    MissingGroupError,
    ReviewCatalog,
    ReviewRecord,
    SaveError,
)

_OCCURRED_AT = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)


def _catalog() -> FixedCatalog:
    return FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id="waste_tank",
                    title="Бак отходов",
                    required=True,
                    defects=(DefectButton(code="dirty", label="Грязь"),),
                ),
                CatalogGroup(
                    group_id="cup",
                    title="Стакан",
                    required=False,
                    defects=(),
                ),
            )
        )
    )


def _batch(*, accepted: bool = True) -> FixedBatches:
    if not accepted:
        return FixedBatches(None)
    return FixedBatches(
        AcceptedBatch(
            batch_id="batch-1",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_OCCURRED_AT,
            files=(
                AcceptedPhotoFile(index=0, content_type="image/jpeg", storage_key="k0"),
                AcceptedPhotoFile(index=1, content_type="image/jpeg", storage_key="k1"),
            ),
        )
    )


def test_group_assignment_keeps_indexes() -> None:
    assignment = GroupAssignment(
        batch_id="batch-1",
        group_id="waste_tank",
        indexes=(0, 1),
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )
    assert assignment.indexes == (0, 1)
    assert AcceptedBatch.__dataclass_fields__["files"] is not None


def test_assign_replaces_live_groups() -> None:
    store = MemoryReviewStore()
    store.replace_assignments(
        "batch-1",
        (
            GroupAssignment(
                batch_id="batch-1",
                group_id="cup",
                indexes=(0,),
                machine_id="m-1",
                technician_id="t-1",
                occurred_at=_OCCURRED_AT,
            ),
        ),
        clear_missing_group_ids=(),
    )
    result = AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0, 1)),),
    )
    assert result.is_ok()
    groups = {item.group_id for item in store.assignments_for_batch("batch-1")}
    assert groups == {"waste_tank"}


def test_assign_repeat_is_idempotent() -> None:
    store = MemoryReviewStore()
    command = AssignBatchGroups(_catalog(), store, _batch())
    first = command.execute("batch-1", (("waste_tank", (0,)), ("cup", (1,))))
    second = command.execute("batch-1", (("waste_tank", (0,)), ("cup", (1,))))
    assert first.is_ok() and second.is_ok()
    assert len(store.assignments_for_batch("batch-1")) == 2


def test_assign_failure_leaves_store_unchanged() -> None:
    store = MemoryReviewStore()
    command = AssignBatchGroups(_catalog(), store, _batch())
    assert command.execute("batch-1", (("waste_tank", (0,)),)).is_ok()
    failed = command.execute("batch-1", (("waste_tank", (0,)), ("missing", (1,))))
    assert failed.is_err()
    assert failed.error is AssignError.UNKNOWN_GROUP
    assert {item.group_id for item in store.assignments_for_batch("batch-1")} == {"waste_tank"}


def test_assign_rejects_duplicate_index_empty_group_and_missing_file() -> None:
    store = MemoryReviewStore()
    command = AssignBatchGroups(_catalog(), store, _batch())
    assert command.execute("batch-1", (("waste_tank", (0,)), ("cup", (0,)))).error is (
        AssignError.DUPLICATE_INDEX
    )
    assert command.execute("batch-1", (("waste_tank", ()),)).error is AssignError.EMPTY_GROUP
    assert command.execute("batch-1", (("waste_tank", (9,)),)).error is (
        AssignError.INDEX_WITHOUT_FILE
    )
    assert store.assignments_for_batch("batch-1") == ()


def test_assign_rejects_batch_that_is_not_accepted() -> None:
    store = MemoryReviewStore()
    result = AssignBatchGroups(_catalog(), store, _batch(accepted=False)).execute(
        "batch-1",
        (("waste_tank", (0,)),),
    )
    assert result.error is AssignError.BATCH_NOT_ACCEPTED


def _human_record(group_id: str) -> ReviewRecord:
    return ReviewRecord(
        batch_id="batch-1",
        group_id=group_id,
        record_kind="human",
        indexes=(0,),
        defects=(DefectMark("dirty", "Грязь"),),
        system_error=False,
        comment="",
        creator_kind="human",
        actor_user_id="user-1",
        saved_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
        group_title="Бак отходов",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def test_missing_required_group_is_idempotent() -> None:
    store = MemoryReviewStore()
    clock = FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC))
    command = RecordMissingRequiredGroup(_catalog(), store, _batch(), clock.now)
    first = command.execute("batch-1", "waste_tank")
    clock.now_value = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
    second = command.execute("batch-1", "waste_tank")
    assert first.is_ok() and second.is_ok()
    assert first.value.saved_at == second.value.saved_at
    assert first.value.creator_kind == "system"
    assert first.value.record_kind == "missing"
    assert first.value.indexes == ()
    assert first.value.group_title == "Бак отходов"
    assert store.find_record("batch-1", "waste_tank") == first.value


def test_missing_required_group_rejects_when_assignment_exists() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0,)),),
    )
    result = RecordMissingRequiredGroup(
        _catalog(), store, _batch(), FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute("batch-1", "waste_tank")
    assert result.error is MissingGroupError.HAS_ASSIGNMENT


def test_missing_required_group_rejects_when_human_record_exists() -> None:
    store = MemoryReviewStore()
    store.save_record(_human_record("waste_tank"))
    result = RecordMissingRequiredGroup(
        _catalog(), store, _batch(), FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute("batch-1", "waste_tank")
    assert result.error is MissingGroupError.HAS_HUMAN_RECORD
    assert store.find_record("batch-1", "waste_tank").creator_kind == "human"


def test_missing_required_group_rejects_optional_and_unknown() -> None:
    store = MemoryReviewStore()
    command = RecordMissingRequiredGroup(
        _catalog(), store, _batch(), FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    )
    assert command.execute("batch-1", "cup").error is MissingGroupError.GROUP_NOT_REQUIRED
    assert command.execute("batch-1", "nope").error is MissingGroupError.GROUP_NOT_REQUIRED
    assert store.list_records() == ()


def test_assign_clears_system_missing_only() -> None:
    store = MemoryReviewStore()
    clock = FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC))
    created = RecordMissingRequiredGroup(_catalog(), store, _batch(), clock.now).execute(
        "batch-1", "waste_tank"
    )
    assert created.is_ok()
    assigned = AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0,)),),
    )
    assert assigned.is_ok()
    assert store.find_record("batch-1", "waste_tank") is None
    assert store.find_assignment("batch-1", "waste_tank") is not None


def test_assign_keeps_human_record_when_group_dropped() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0,)), ("cup", (1,))),
    )
    store.save_record(_human_record("waste_tank"))
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("cup", (1,)),),
    )
    assert store.find_assignment("batch-1", "waste_tank") is None
    assert store.find_record("batch-1", "waste_tank").creator_kind == "human"


def _catalog_without_dirty() -> FixedCatalog:
    return FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id="waste_tank",
                    title="Бак отходов",
                    required=True,
                    defects=(),
                ),
                CatalogGroup(
                    group_id="cup",
                    title="Стакан",
                    required=False,
                    defects=(),
                ),
            )
        )
    )


def test_save_copies_indexes_and_new_label() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0, 1)),))
    saved = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
    )
    assert saved.is_ok()
    assert saved.value.indexes == (0, 1)
    assert saved.value.defects == (DefectMark("dirty", "Грязь"),)
    assert saved.value.creator_kind == "human"
    assert saved.value.actor_user_id == "user-7"


def test_save_with_frame_index_scopes_record_to_that_frame() -> None:
    # happy — mark on frame 0 does not become the record for frame 1
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0, 1)),))
    command = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    )
    first = command.execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
        frame_index=0,
    )
    assert first.is_ok()
    assert first.value.indexes == (0,)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is not None
    assert store.find_frame_record("batch-1", "waste_tank", 1) is None


def test_save_clear_one_frame_leaves_sibling_frame_marks() -> None:
    # edge — independent per-frame records
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0, 1)),))
    command = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    )
    assert command.execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
        frame_index=0,
    ).is_ok()
    assert command.execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
        frame_index=1,
    ).is_ok()
    ClearReviewRecord(store).execute("batch-1", "waste_tank", frame_index=0)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is None
    remaining = store.find_frame_record("batch-1", "waste_tank", 1)
    assert remaining is not None
    assert {mark.code for mark in remaining.defects} == {"dirty"}


def test_save_rejects_frame_index_outside_assignment() -> None:
    # error
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0, 1)),))
    result = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
        frame_index=9,
    )
    assert result.error is SaveError.INVALID_FRAME_INDEX


def _legacy_group_human(*, indexes: tuple[int, ...] = (0, 1)) -> ReviewRecord:
    return ReviewRecord(
        batch_id="batch-1",
        group_id="waste_tank",
        record_kind="human",
        indexes=indexes,
        defects=(DefectMark(code="dirty", label="Грязь"),),
        system_error=False,
        comment="legacy",
        creator_kind="human",
        actor_user_id="user-legacy",
        saved_at=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        group_title="Бак отходов",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def test_clear_frame_detaches_from_legacy_group_record() -> None:
    # edge — clear_record(frame_index) must not leave legacy covering that frame
    store = MemoryReviewStore()
    store.save_record(_legacy_group_human(indexes=(0, 1)))
    assert store.find_frame_record("batch-1", "waste_tank", 0) is not None
    ClearReviewRecord(store).execute("batch-1", "waste_tank", frame_index=0)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is None
    sibling = store.find_frame_record("batch-1", "waste_tank", 1)
    assert sibling is not None
    assert sibling.indexes == (1,)
    assert sibling.comment == "legacy"


def test_clear_last_legacy_frame_deletes_legacy_doc() -> None:
    # edge — empty remaining indexes → drop legacy
    store = MemoryReviewStore()
    store.save_record(_legacy_group_human(indexes=(0,)))
    ClearReviewRecord(store).execute("batch-1", "waste_tank", frame_index=0)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is None
    assert store.find_record("batch-1", "waste_tank") is None


def test_save_single_frame_detaches_from_legacy_group_record() -> None:
    # edge — exact frame doc owns the frame; sibling keeps legacy marks
    store = MemoryReviewStore()
    store.save_record(_legacy_group_human(indexes=(0, 1)))
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0, 1)),))
    saved = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 9, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="exact",
        frame_index=0,
    )
    assert saved.is_ok()
    exact = store.find_frame_record("batch-1", "waste_tank", 0)
    assert exact is not None
    assert exact.indexes == (0,)
    assert exact.comment == "exact"
    sibling = store.find_frame_record("batch-1", "waste_tank", 1)
    assert sibling is not None
    assert sibling.indexes == (1,)
    assert sibling.comment == "legacy"


def test_save_keeps_label_after_catalog_code_dropped() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0,)),))
    SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="было",
    )
    catalog = _catalog_without_dirty()
    again = SaveReviewRecord(
        catalog, store, FixedClock(datetime(2026, 9, 23, 9, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-8",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=True,
        comment="стало",
    )
    assert again.is_ok()
    assert again.value.defects == (DefectMark("dirty", "Грязь"),)
    assert again.value.system_error is True
    assert again.value.actor_user_id == "user-8"
    assert again.value.comment == "стало"


def test_save_rejects_without_live_assignment() -> None:
    store = MemoryReviewStore()
    result = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=("dirty",),
        system_error=False,
        comment="",
    )
    assert result.error is SaveError.NO_LIVE_ASSIGNMENT


def test_save_rejects_empty_marks_and_unknown_code() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0,)),))
    command = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    )
    assert (
        command.execute(
            actor_user_id="user-7",
            batch_id="batch-1",
            group_id="waste_tank",
            defect_codes=(),
            system_error=False,
            comment="только текст",
        ).error
        is SaveError.NO_MARKS
    )
    assert (
        command.execute(
            actor_user_id="user-7",
            batch_id="batch-1",
            group_id="waste_tank",
            defect_codes=("nope",),
            system_error=False,
            comment="",
        ).error
        is SaveError.UNKNOWN_DEFECT
    )


def test_system_error_is_not_a_defect_code() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0,)),))
    saved = SaveReviewRecord(
        _catalog(), store, FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC)).now
    ).execute(
        actor_user_id="user-7",
        batch_id="batch-1",
        group_id="waste_tank",
        defect_codes=(),
        system_error=True,
        comment="",
    )
    assert saved.is_ok()
    assert saved.value.defects == ()
    assert saved.value.system_error is True
    assert all(mark.code != "system_error" for mark in saved.value.defects)


def test_clear_absent_record_is_success() -> None:
    store = MemoryReviewStore()
    result = ClearReviewRecord(store).execute("batch-1", "waste_tank")
    assert result.is_ok()
    assert store.find_record("batch-1", "waste_tank") is None


def test_clear_drops_human_record_and_keeps_assignment() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute("batch-1", (("waste_tank", (0,)),))
    store.save_record(_human_record("waste_tank"))
    assert ClearReviewRecord(store).execute("batch-1", "waste_tank").is_ok()
    assert store.find_record("batch-1", "waste_tank") is None
    assert store.find_assignment("batch-1", "waste_tank") is not None


def test_loading_accept_sources_do_not_reference_visit_photo_review() -> None:
    from pathlib import Path

    roots = (
        Path("src/application/photo_batches"),
        Path("src/application/photo_integrity"),
        Path("src/application/outbox"),
        Path("src/interfaces/telegram"),
    )
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "visit_photo_review" not in text, path.as_posix()


def test_relocate_moves_one_index_and_keeps_neighbor() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0,)), ("cup", (1,))),
    )
    result = RelocateBatchIndex(_catalog(), store, _batch()).execute("batch-1", 0, "cup")
    assert result.is_ok()
    by_group = {item.group_id: item.indexes for item in store.assignments_for_batch("batch-1")}
    assert by_group == {"cup": (0, 1)}
    assert store.find_assignment("batch-1", "waste_tank") is None


def test_relocate_to_target_clears_only_target_system_missing() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("cup", (0,)),),
    )
    clock = FixedClock(datetime(2026, 9, 23, 8, 0, tzinfo=UTC))
    RecordMissingRequiredGroup(_catalog(), store, _batch(), clock.now).execute(
        "batch-1", "waste_tank"
    )
    store.save_record(
        ReviewRecord(
            batch_id="batch-1",
            group_id="cup",
            record_kind="missing",
            indexes=(),
            defects=(),
            system_error=True,
            comment="",
            creator_kind="system",
            actor_user_id=None,
            saved_at=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
            group_title="Стакан",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_OCCURRED_AT,
        )
    )
    result = RelocateBatchIndex(_catalog(), store, _batch()).execute("batch-1", 0, "waste_tank")
    assert result.is_ok()
    assert store.find_record("batch-1", "waste_tank") is None
    assert store.find_record("batch-1", "cup") is not None
    assert store.find_record("batch-1", "cup").record_kind == "missing"


def test_relocate_keeps_human_record_on_target() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("cup", (0,)),),
    )
    human = _human_record("waste_tank")
    store.save_record(human)
    result = RelocateBatchIndex(_catalog(), store, _batch()).execute("batch-1", 0, "waste_tank")
    assert result.is_ok()
    assert store.find_record("batch-1", "waste_tank") == human
    assert store.find_assignment("batch-1", "waste_tank").indexes == (0,)


def test_relocate_without_target_removes_index_from_all_groups() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("waste_tank", (0, 1)),),
    )
    result = RelocateBatchIndex(_catalog(), store, _batch()).execute("batch-1", 0, None)
    assert result.is_ok()
    assert store.find_assignment("batch-1", "waste_tank").indexes == (1,)
    assert store.records_for_batch("batch-1") == ()


def test_relocate_rejects_unknown_group_and_index_without_file() -> None:
    store = MemoryReviewStore()
    AssignBatchGroups(_catalog(), store, _batch()).execute(
        "batch-1",
        (("cup", (0,)),),
    )
    command = RelocateBatchIndex(_catalog(), store, _batch())
    before = store.assignments_for_batch("batch-1")
    assert command.execute("batch-1", 0, "missing").error is AssignError.UNKNOWN_GROUP
    assert command.execute("batch-1", 9, "waste_tank").error is (AssignError.INDEX_WITHOUT_FILE)
    assert store.assignments_for_batch("batch-1") == before


def test_relocate_rejects_batch_not_accepted() -> None:
    store = MemoryReviewStore()
    result = RelocateBatchIndex(_catalog(), store, _batch(accepted=False)).execute(
        "batch-1", 0, "cup"
    )
    assert result.error is AssignError.BATCH_NOT_ACCEPTED


def test_record_frame_view_is_idempotent() -> None:
    store = MemoryReviewStore()
    clock = FixedClock(datetime(2026, 10, 13, 12, 0, tzinfo=UTC))
    command = RecordFrameView(store, clock.now)

    first = command.execute(batch_id="batch-1", index=0, actor_user_id="user-a")
    second = command.execute(batch_id="batch-1", index=0, actor_user_id="user-a")

    assert isinstance(first, FrameView)
    assert first == second
    assert first.batch_id == "batch-1"
    assert first.index == 0
    assert first.actor_user_id == "user-a"
    assert first.viewed_at == clock.now_value
    assert store.list_frame_views() == (first,)


def test_record_frame_view_keeps_first_actor_on_repeat() -> None:
    store = MemoryReviewStore()
    clock = FixedClock(datetime(2026, 10, 13, 12, 0, tzinfo=UTC))
    command = RecordFrameView(store, clock.now)

    first = command.execute(batch_id="batch-1", index=1, actor_user_id="user-a")
    clock.now_value = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
    second = command.execute(batch_id="batch-1", index=1, actor_user_id="user-b")

    assert second == first
    assert second.actor_user_id == "user-a"
    assert second.viewed_at == datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    assert store.find_frame_view("batch-1", 1) == first
    assert store.list_frame_views() == (first,)


def test_record_frame_view_does_not_create_review_record() -> None:
    store = MemoryReviewStore()
    clock = FixedClock(datetime(2026, 10, 13, 12, 0, tzinfo=UTC))

    view = RecordFrameView(store, clock.now).execute(
        batch_id="batch-1",
        index=0,
        actor_user_id="user-a",
    )

    assert isinstance(view, FrameView)
    assert store.list_records() == ()
    assert store.find_record("batch-1", "waste_tank") is None
    assert store.list_frame_views() == (view,)


def test_update_group_defects_rewrites_catalog_json() -> None:
    catalog = _catalog()
    other = catalog.load().group("cup")
    assert other is not None
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (
            ("dirty", "Пыль"),
            ("leak", ""),
            ("  ", "  "),
            ("rust", "Ржавчина"),
        ),
    )
    assert result.is_ok()
    updated = catalog.load().group("waste_tank")
    assert updated is not None
    assert updated.title == "Бак отходов"
    assert updated.required is True
    assert updated.defects == (
        DefectButton(code="dirty", label="Пыль"),
        DefectButton(code="rust", label="Ржавчина"),
    )
    assert catalog.load().group("cup") == other


def test_update_group_defects_slugs_code_from_label_on_create() -> None:
    # happy — ISS-019
    catalog = _catalog()
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (("", "Грязь на стенке"),),
    )
    assert result.is_ok()
    updated = catalog.load().group("waste_tank")
    assert updated is not None
    assert updated.defects == (DefectButton(code="gryaz-na-stenke", label="Грязь на стенке"),)


def test_update_group_defects_rename_keeps_existing_code() -> None:
    # edge
    catalog = _catalog()
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (("dirty", "Совсем другая подпись"),),
    )
    assert result.is_ok()
    updated = catalog.load().group("waste_tank")
    assert updated is not None
    assert updated.defects == (DefectButton(code="dirty", label="Совсем другая подпись"),)


def test_update_group_defects_skips_empty_label() -> None:
    # error / reject empty label rows
    catalog = _catalog()
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (("", ""), ("kept", "")),
    )
    assert result.is_ok()
    updated = catalog.load().group("waste_tank")
    assert updated is not None
    assert updated.defects == ()


def test_update_group_defects_rejects_photo_only() -> None:
    catalog = _catalog()
    before = catalog.load()
    for group_id in ("trash", "poor_quality"):
        result = UpdateGroupDefects(catalog).execute(
            group_id,
            (("x", "y"),),
        )
        assert result.is_err()
        assert result.error is UpdateGroupDefectsError.PHOTO_ONLY_GROUP
    assert catalog.load() == before


def test_update_group_defects_rejects_duplicate_code() -> None:
    catalog = _catalog()
    before = catalog.load()
    result = UpdateGroupDefects(catalog).execute(
        "waste_tank",
        (("dirty", "A"), ("dirty", "B")),
    )
    assert result.is_err()
    assert result.error is UpdateGroupDefectsError.DUPLICATE_CODE
    assert catalog.load() == before


def test_update_group_defects_propagates_catalog_unavailable() -> None:
    catalog = FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(
                    group_id="waste_tank",
                    title="Бак отходов",
                    required=True,
                    defects=(),
                ),
            )
        ),
        unavailable=True,
    )
    with pytest.raises(CatalogUnavailable):
        UpdateGroupDefects(catalog).execute("waste_tank", (("dirty", "Грязь"),))


def test_write_group_avatar_stores_bytes() -> None:
    writer = MemoryGroupAvatarWriter()
    jpeg = b"\xff\xd8\xff" + b"jpeg-body"
    result = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=jpeg,
        content_type="image/jpeg",
    )
    assert result.is_ok()
    avatar = writer.read_avatar("waste_tank")
    assert avatar is not None
    assert avatar.content == jpeg
    assert avatar.content_type == "image/jpeg"


def test_write_group_avatar_rejects_without_pack_dir() -> None:
    writer = MemoryGroupAvatarWriter(pack_dir_configured=False)
    result = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=b"\xff\xd8\xff" + b"x",
        content_type="image/jpeg",
    )
    assert result.is_err()
    assert result.error is WriteGroupAvatarError.PACK_DIR_UNAVAILABLE
    assert writer.write_calls == []


def test_write_group_avatar_rejects_empty_or_invalid_bytes() -> None:
    writer = MemoryGroupAvatarWriter()
    empty = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=b"",
        content_type="image/jpeg",
    )
    invalid = WriteGroupAvatar(writer).execute(
        group_id="waste_tank",
        content=b"not-an-image",
        content_type="image/jpeg",
    )
    assert empty.error is WriteGroupAvatarError.INVALID_IMAGE
    assert invalid.error is WriteGroupAvatarError.INVALID_IMAGE
    assert writer.write_calls == []


_JPEG_BODY = b"\xff\xd8\xff" + b"learned-jpeg"


def test_append_learned_writes_via_port() -> None:
    writer = MemoryLearnedReferenceWriter()
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=2,
        content=_JPEG_BODY,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_ok()
    assert writer.append_calls == [
        {
            "group_id": "waste_tank",
            "batch_id": "batch-1",
            "index": 2,
            "content": _JPEG_BODY,
            "content_type": "image/jpeg",
            "max_per_group": 200,
        }
    ]


def test_append_learned_skips_at_cap() -> None:
    writer = MemoryLearnedReferenceWriter(skip_reason="skip_cap")
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=0,
        content=_JPEG_BODY,
        content_type="image/jpeg",
        max_per_group=1,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.SKIP_CAP


def test_append_learned_skips_duplicate_hash() -> None:
    writer = MemoryLearnedReferenceWriter(skip_reason="skip_dup")
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=0,
        content=_JPEG_BODY,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.SKIP_DUP


def test_append_learned_pack_unavailable() -> None:
    writer = MemoryLearnedReferenceWriter(pack_dir_configured=False)
    result = AppendLearnedReference(writer).execute(
        group_id="waste_tank",
        batch_id="batch-1",
        index=0,
        content=_JPEG_BODY,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.PACK_UNAVAILABLE


def test_append_learned_rejects_unsafe_group_id() -> None:
    writer = MemoryLearnedReferenceWriter()
    result = AppendLearnedReference(writer).execute(
        group_id="../secret",
        batch_id="batch-1",
        index=0,
        content=_JPEG_BODY,
        content_type="image/jpeg",
        max_per_group=200,
    )
    assert result.is_err()
    assert result.error is AppendLearnedReferenceError.INVALID
    assert writer.append_calls == []
