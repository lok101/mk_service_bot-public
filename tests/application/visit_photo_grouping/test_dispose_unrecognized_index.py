from __future__ import annotations

from datetime import UTC, datetime

from beartype import beartype
from tests.application.visit_photo_review.fakes import (
    FixedBatches,
    FixedCatalog,
    FixedClock,
    MemoryLearnedReferenceWriter,
    MemoryReviewStore,
)

from src.application.visit_photo_grouping import (
    DisposeAction,
    DisposeError,
    DisposeUnrecognizedIndex,
)
from src.application.visit_photo_review import (
    AppendLearnedReference,
    RecordMissingRequiredGroup,
    RelocateBatchIndex,
)
from src.application.visit_photo_review.ports import AcceptedBatch, AcceptedPhotoFile
from src.application.visit_photo_review.queries import ReviewQueries
from src.domain.visit_photo_review import (
    CatalogGroup,
    DefectMark,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)


class _MemoryPhotoBytes:
    def __init__(self, payloads: dict[str, bytes] | None = None, *, fail: bool = False) -> None:
        self._payloads = payloads or {}
        self.fail = fail
        self.calls: list[str] = []

    @beartype
    def get_bytes(self, storage_key: str) -> bytes:
        self.calls.append(storage_key)
        if self.fail:
            raise OSError("storage down")
        return self._payloads[storage_key]


_OCCURRED_AT = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
_SAVED_AT = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


def _catalog(*, extra_required: tuple[CatalogGroup, ...] = ()) -> FixedCatalog:
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
                *extra_required,
                CatalogGroup(
                    group_id="unrecognized",
                    title="Не удалось определить",
                    required=False,
                    defects=(),
                ),
                CatalogGroup(
                    group_id="poor_quality",
                    title="Некачественные фото",
                    required=False,
                    defects=(),
                ),
            )
        )
    )


def _batch(*, file_count: int = 2) -> FixedBatches:
    files = tuple(
        AcceptedPhotoFile(index=index, content_type="image/jpeg", storage_key=f"k{index}")
        for index in range(file_count)
    )
    return FixedBatches(
        AcceptedBatch(
            batch_id="batch-1",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_OCCURRED_AT,
            files=files,
        )
    )


def _put_assignment(
    store: MemoryReviewStore,
    group_id: str,
    indexes: tuple[int, ...],
) -> None:
    kept = tuple(
        item for item in store.assignments_for_batch("batch-1") if item.group_id != group_id
    )
    store.replace_assignments(
        "batch-1",
        (
            *kept,
            GroupAssignment(
                batch_id="batch-1",
                group_id=group_id,
                indexes=indexes,
                machine_id="m-1",
                technician_id="t-1",
                occurred_at=_OCCURRED_AT,
            ),
        ),
        clear_missing_group_ids=(),
    )


def _dispose(
    store: MemoryReviewStore,
    batches: FixedBatches,
    catalog: FixedCatalog | None = None,
    *,
    append_writer: MemoryLearnedReferenceWriter | None = None,
    photo_bytes: _MemoryPhotoBytes | None = None,
    learned_max_per_group: int = 200,
) -> DisposeUnrecognizedIndex:
    catalog = catalog or _catalog()
    append = AppendLearnedReference(append_writer) if append_writer is not None else None
    return DisposeUnrecognizedIndex(
        catalog=catalog,
        store=store,
        batches=batches,
        relocate=RelocateBatchIndex(catalog, store, batches),
        missing=RecordMissingRequiredGroup(catalog, store, batches, FixedClock(_SAVED_AT).now),
        append_learned=append,
        photo_bytes=photo_bytes,
        learned_max_per_group=learned_max_per_group,
    )


_JPEG = b"\xff\xd8\xff" + b"frame-0"


def test_dispose_content_moves_one_index_from_unrecognized() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    result = _dispose(store, batches).execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    assert result.is_ok()
    by_group = {item.group_id: item.indexes for item in store.assignments_for_batch("batch-1")}
    assert by_group == {"cup": (0,), "unrecognized": (1,)}
    assert store.records_for_batch("batch-1") == ()


def test_dispose_last_unrecognized_writes_missing_for_empty_required() -> None:
    store = MemoryReviewStore()
    batches = _batch(file_count=1)
    _put_assignment(store, "unrecognized", (0,))
    result = _dispose(store, batches).execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    assert result.is_ok()
    assert store.find_assignment("batch-1", "unrecognized") is None
    assert store.find_assignment("batch-1", "cup") is not None
    assert store.find_assignment("batch-1", "cup").indexes == (0,)
    missing = store.find_record("batch-1", "waste_tank")
    assert missing is not None
    assert missing.record_kind == "missing"
    assert store.find_record("batch-1", "cup") is None


def test_dispose_trash_keeps_file_hides_from_read_photo() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    catalog = _catalog()
    _put_assignment(store, "unrecognized", (0, 1))
    result = _dispose(store, batches, catalog).execute("batch-1", 0, DisposeAction.TRASH, None)
    assert result.is_ok()
    batch = batches.get("batch-1")
    assert batch is not None
    assert any(item.index == 0 for item in batch.files)
    assert ReviewQueries(catalog, store, batches).read_photo("batch-1", 0) is None
    assert store.records_for_batch("batch-1") == ()
    by_group = {item.group_id: item.indexes for item in store.assignments_for_batch("batch-1")}
    assert by_group == {"unrecognized": (1,)}


def test_dispose_poor_quality_does_not_create_record() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    result = _dispose(store, batches).execute("batch-1", 0, DisposeAction.POOR_QUALITY, None)
    assert result.is_ok()
    assert store.find_assignment("batch-1", "poor_quality") is not None
    assert store.find_assignment("batch-1", "poor_quality").indexes == (0,)
    assert store.records_for_batch("batch-1") == ()
    assert store.find_record("batch-1", "poor_quality") is None


def test_dispose_partial_leaves_missing_deferred() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    result = _dispose(store, batches).execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    assert result.is_ok()
    assert store.find_assignment("batch-1", "unrecognized") is not None
    assert store.records_for_batch("batch-1") == ()


def test_dispose_repeat_same_outcome_is_ok() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    dispose = _dispose(store, batches)
    first = dispose.execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    second = dispose.execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    assert first.is_ok() and second.is_ok()
    by_group = {item.group_id: item.indexes for item in store.assignments_for_batch("batch-1")}
    assert by_group == {"cup": (0,), "unrecognized": (1,)}


def test_dispose_missing_cycle_skips_has_human_record() -> None:
    store = MemoryReviewStore()
    batches = _batch(file_count=1)
    catalog = _catalog(
        extra_required=(
            CatalogGroup(
                group_id="front",
                title="Фасад",
                required=True,
                defects=(),
            ),
        )
    )
    _put_assignment(store, "unrecognized", (0,))
    store.save_record(
        ReviewRecord(
            batch_id="batch-1",
            group_id="waste_tank",
            record_kind="human",
            indexes=(),
            defects=(DefectMark("dirty", "Грязь"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="user-1",
            saved_at=_SAVED_AT,
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_OCCURRED_AT,
        )
    )
    result = _dispose(store, batches, catalog).execute("batch-1", 0, DisposeAction.CONTENT, "cup")
    assert result.is_ok()
    assert store.find_record("batch-1", "waste_tank").record_kind == "human"
    front = store.find_record("batch-1", "front")
    assert front is not None
    assert front.record_kind == "missing"


def test_dispose_rejects_index_already_in_content_group() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "cup", (0,))
    before = store.assignments_for_batch("batch-1")
    result = _dispose(store, batches).execute("batch-1", 0, DisposeAction.CONTENT, "waste_tank")
    assert result.is_err()
    assert result.error is DisposeError.INDEX_NOT_IN_UNRECOGNIZED
    assert store.assignments_for_batch("batch-1") == before


def test_dispose_rejects_content_target_reserved() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0,))
    dispose = _dispose(store, batches)
    before = store.assignments_for_batch("batch-1")
    for target in ("unrecognized", "poor_quality"):
        result = dispose.execute("batch-1", 0, DisposeAction.CONTENT, target)
        assert result.is_err()
        assert result.error is DisposeError.INVALID_TARGET
    assert store.assignments_for_batch("batch-1") == before


def test_dispose_content_appends_learned() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    writer = MemoryLearnedReferenceWriter()
    photos = _MemoryPhotoBytes({"k0": _JPEG, "k1": _JPEG})
    result = _dispose(store, batches, append_writer=writer, photo_bytes=photos).execute(
        "batch-1",
        0,
        DisposeAction.CONTENT,
        "cup",
    )
    assert result.is_ok()
    assert writer.append_calls == [
        {
            "group_id": "cup",
            "batch_id": "batch-1",
            "index": 0,
            "content": _JPEG,
            "content_type": "image/jpeg",
            "max_per_group": 200,
        }
    ]
    assert photos.calls == ["k0"]


def test_dispose_trash_skips_append() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    writer = MemoryLearnedReferenceWriter()
    photos = _MemoryPhotoBytes({"k0": _JPEG})
    result = _dispose(store, batches, append_writer=writer, photo_bytes=photos).execute(
        "batch-1",
        0,
        DisposeAction.TRASH,
        None,
    )
    assert result.is_ok()
    assert writer.append_calls == []
    assert photos.calls == []


def test_dispose_poor_quality_skips_append() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    writer = MemoryLearnedReferenceWriter()
    photos = _MemoryPhotoBytes({"k0": _JPEG})
    result = _dispose(store, batches, append_writer=writer, photo_bytes=photos).execute(
        "batch-1",
        0,
        DisposeAction.POOR_QUALITY,
        None,
    )
    assert result.is_ok()
    assert writer.append_calls == []
    assert photos.calls == []


def test_dispose_ok_when_append_fails() -> None:
    store = MemoryReviewStore()
    batches = _batch()
    _put_assignment(store, "unrecognized", (0, 1))
    writer = MemoryLearnedReferenceWriter(raise_os_error=True)
    photos = _MemoryPhotoBytes({"k0": _JPEG})
    result = _dispose(store, batches, append_writer=writer, photo_bytes=photos).execute(
        "batch-1",
        0,
        DisposeAction.CONTENT,
        "cup",
    )
    assert result.is_ok()
    by_group = {item.group_id: item.indexes for item in store.assignments_for_batch("batch-1")}
    assert by_group == {"cup": (0,), "unrecognized": (1,)}
    assert writer.append_calls  # attempted
