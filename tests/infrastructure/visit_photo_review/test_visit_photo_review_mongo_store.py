from __future__ import annotations

from datetime import UTC, datetime

import mongomock
import pytest

from src.domain.visit_photo_review import DefectMark, FrameView, GroupAssignment, ReviewRecord
from src.infrastructure.visit_photo_review.mongo_store import MongoReviewStore

_OCCURRED_AT = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
_SAVED_AT = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
_VIEWED_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _assignment(group_id: str, indexes: tuple[int, ...]) -> GroupAssignment:
    return GroupAssignment(
        batch_id="batch-1",
        group_id=group_id,
        indexes=indexes,
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def _human(group_id: str, comment: str = "") -> ReviewRecord:
    return ReviewRecord(
        batch_id="batch-1",
        group_id=group_id,
        record_kind="human",
        indexes=(0,),
        defects=(DefectMark(code="dirty", label="Грязь"),),
        system_error=False,
        comment=comment,
        creator_kind="human",
        actor_user_id="u-1",
        saved_at=_SAVED_AT,
        group_title="Бак",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def _missing(group_id: str) -> ReviewRecord:
    return ReviewRecord(
        batch_id="batch-1",
        group_id=group_id,
        record_kind="missing",
        indexes=(),
        defects=(),
        system_error=False,
        comment="",
        creator_kind="system",
        actor_user_id=None,
        saved_at=_SAVED_AT,
        group_title="Бак",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def test_mongo_assignment_unique_on_batch_and_group() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.replace_assignments(
        "batch-1", (_assignment("waste_tank", (0,)),), clear_missing_group_ids=()
    )
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0, 1)),),
        clear_missing_group_ids=(),
    )
    found = store.find_assignment("batch-1", "waste_tank")
    assert found is not None
    assert found.indexes == (0, 1)
    assert store.assignments_for_batch("batch-1")[0].indexes == (0, 1)


def test_mongo_record_unique_on_batch_and_group() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_human("waste_tank"))
    store.save_record(_human("waste_tank", comment="второе"))
    found = store.find_record("batch-1", "waste_tank")
    assert found is not None
    assert found.comment == "второе"


def test_mongo_replace_drops_groups_omitted_from_call() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)), _assignment("cup", (1,))),
        clear_missing_group_ids=(),
    )
    store.replace_assignments(
        "batch-1",
        (_assignment("cup", (1,)),),
        clear_missing_group_ids=(),
    )
    assert store.find_assignment("batch-1", "waste_tank") is None
    assert store.find_assignment("batch-1", "cup") is not None


def test_mongo_replace_clears_only_system_missing_for_named_groups() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_missing("waste_tank"))
    store.save_record(_human("cup"))
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)),),
        clear_missing_group_ids=("waste_tank",),
    )
    assert store.find_record("batch-1", "waste_tank") is None
    assert store.find_record("batch-1", "cup") is not None


def test_mongo_assignment_and_record_share_key_as_two_documents() -> None:
    collection = mongomock.MongoClient().db.visit_photo_reviews
    store = MongoReviewStore(collection)
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)),),
        clear_missing_group_ids=(),
    )
    store.save_record(_human("waste_tank"))
    assert store.find_assignment("batch-1", "waste_tank") is not None
    found = store.find_record("batch-1", "waste_tank")
    assert found is not None
    assert found.record_kind == "human"
    assert collection.count_documents({"batch_id": "batch-1"}) == 2


def test_mongo_replace_keeps_human_record_when_group_is_in_clear_list() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_human("waste_tank"))
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)),),
        clear_missing_group_ids=("waste_tank",),
    )
    found = store.find_record("batch-1", "waste_tank")
    assert found is not None
    assert found.record_kind == "human"
    assert store.find_assignment("batch-1", "waste_tank") is not None


def _frame_view(*, index: int = 0, actor: str = "user-a") -> FrameView:
    return FrameView(
        batch_id="batch-1",
        index=index,
        actor_user_id=actor,
        viewed_at=_VIEWED_AT,
    )


def test_mongo_frame_view_round_trip() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    view = _frame_view(index=2)
    store.save_frame_view(view)
    found = store.find_frame_view("batch-1", 2)
    assert found == view
    assert store.list_frame_views() == (view,)


def test_mongo_frame_view_idempotent_second_save() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    first = _frame_view(index=0, actor="user-a")
    second = FrameView(
        batch_id="batch-1",
        index=0,
        actor_user_id="user-b",
        viewed_at=datetime(2026, 10, 13, 13, 0, tzinfo=UTC),
    )
    store.save_frame_view(first)
    store.save_frame_view(second)
    found = store.find_frame_view("batch-1", 0)
    assert found == second
    assert len(store.list_frame_views()) == 1


def test_mongo_frame_view_unique_on_batch_and_index() -> None:
    collection = mongomock.MongoClient().db.visit_photo_reviews
    store = MongoReviewStore(collection)
    store.save_frame_view(_frame_view(index=0))
    store.save_frame_view(_frame_view(index=1))
    store.save_record(_human("waste_tank"))
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)),),
        clear_missing_group_ids=(),
    )
    assert collection.count_documents({"kind": "frame_view"}) == 2
    assert collection.count_documents({"kind": "record"}) == 1
    assert collection.count_documents({"kind": "assignment"}) == 1
    assert store.find_frame_view("batch-1", 0) is not None
    assert store.find_frame_view("batch-1", 1) is not None
    assert store.find_record("batch-1", "waste_tank") is not None
    assert store.find_assignment("batch-1", "waste_tank") is not None


def _legacy_human(*, indexes: tuple[int, ...] = (0, 1)) -> ReviewRecord:
    return ReviewRecord(
        batch_id="batch-1",
        group_id="waste_tank",
        record_kind="human",
        indexes=indexes,
        defects=(DefectMark(code="dirty", label="Грязь"),),
        system_error=False,
        comment="legacy",
        creator_kind="human",
        actor_user_id="u-1",
        saved_at=_SAVED_AT,
        group_title="Бак",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED_AT,
    )


def test_mongo_clear_frame_detaches_from_legacy_group_record() -> None:
    # edge — frame clear must rewrite/delete legacy human without frame_index
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_legacy_human(indexes=(0, 1)))
    assert store.find_frame_record("batch-1", "waste_tank", 0) is not None
    store.clear_record("batch-1", "waste_tank", frame_index=0)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is None
    sibling = store.find_frame_record("batch-1", "waste_tank", 1)
    assert sibling is not None
    assert sibling.indexes == (1,)
    assert sibling.comment == "legacy"


def test_mongo_clear_last_legacy_frame_deletes_legacy_doc() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_legacy_human(indexes=(0,)))
    store.clear_record("batch-1", "waste_tank", frame_index=0)
    assert store.find_frame_record("batch-1", "waste_tank", 0) is None
    assert store.find_record("batch-1", "waste_tank") is None


def test_mongo_save_single_frame_detaches_from_legacy_group_record() -> None:
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.save_record(_legacy_human(indexes=(0, 1)))
    exact = _human("waste_tank", comment="exact")
    store.save_record(exact)
    found = store.find_frame_record("batch-1", "waste_tank", 0)
    assert found is not None
    assert found.indexes == (0,)
    assert found.comment == "exact"
    sibling = store.find_frame_record("batch-1", "waste_tank", 1)
    assert sibling is not None
    assert sibling.indexes == (1,)
    assert sibling.comment == "legacy"


def test_mongo_store_upgrades_legacy_unique_index_options() -> None:
    collection = mongomock.MongoClient().db.visit_photo_reviews
    collection.create_index(
        [("kind", 1), ("batch_id", 1), ("group_id", 1)],
        unique=True,
    )
    store = MongoReviewStore(collection)
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)),),
        clear_missing_group_ids=(),
    )
    store.save_frame_view(_frame_view(index=0))
    assert store.find_assignment("batch-1", "waste_tank") is not None
    assert store.find_frame_view("batch-1", 0) is not None


class _FailAfterNReplaceCollection:
    """Proxy: fail on N-th replace_one to simulate mid-replace crash."""

    def __init__(self, inner: object, *, fail_on_call: int) -> None:
        self._inner = inner
        self._fail_on_call = fail_on_call
        self._replace_calls = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def replace_one(self, *args: object, **kwargs: object) -> object:
        self._replace_calls += 1
        if self._replace_calls == self._fail_on_call:
            msg = "simulated mid-replace failure"
            raise RuntimeError(msg)
        return self._inner.replace_one(*args, **kwargs)  # type: ignore[no-any-return]

    def insert_many(self, *args: object, **kwargs: object) -> object:
        self._replace_calls += 1
        if self._replace_calls == self._fail_on_call:
            msg = "simulated mid-replace failure"
            raise RuntimeError(msg)
        return self._inner.insert_many(*args, **kwargs)  # type: ignore[no-any-return]


def test_mongo_replace_assignments_keeps_prior_on_mid_fail() -> None:
    # error: crash mid-replace must not leave an empty assignment window
    real = mongomock.MongoClient().db.visit_photo_reviews
    store = MongoReviewStore(real)
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)), _assignment("cup", (1,))),
        clear_missing_group_ids=(),
    )
    flaky = _FailAfterNReplaceCollection(real, fail_on_call=1)
    broken = MongoReviewStore.__new__(MongoReviewStore)
    broken._collection = flaky  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="simulated mid-replace"):
        broken.replace_assignments(
            "batch-1",
            (_assignment("door", (2,)), _assignment("cup", (1, 3))),
            clear_missing_group_ids=(),
        )
    remaining = store.assignments_for_batch("batch-1")
    assert remaining, "assignments must not be empty after mid-replace failure"
    assert store.find_assignment("batch-1", "waste_tank") is not None
    assert store.find_assignment("batch-1", "cup") is not None


def test_mongo_replace_assignments_swaps_without_empty_window() -> None:
    # happy: upsert-then-delete-stale ends with only the new set
    store = MongoReviewStore(mongomock.MongoClient().db.visit_photo_reviews)
    store.replace_assignments(
        "batch-1",
        (_assignment("waste_tank", (0,)), _assignment("cup", (1,))),
        clear_missing_group_ids=(),
    )
    store.replace_assignments(
        "batch-1",
        (_assignment("door", (2,)),),
        clear_missing_group_ids=(),
    )
    assert store.find_assignment("batch-1", "waste_tank") is None
    assert store.find_assignment("batch-1", "cup") is None
    found = store.find_assignment("batch-1", "door")
    assert found is not None
    assert found.indexes == (2,)
