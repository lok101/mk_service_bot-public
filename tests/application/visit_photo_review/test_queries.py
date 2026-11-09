from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from tests.application.visit_photo_review.fakes import FixedCatalog, MemoryReviewStore

from src.application.visit_photo_review.ports import (
    AcceptedBatch,
    AcceptedPhotoFile,
    CatalogUnavailable,
)
from src.application.visit_photo_review.queries import ReviewQueries
from src.domain.visit_photo_review import (
    CatalogGroup,
    DefectButton,
    DefectMark,
    FrameView,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)

_LATE = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
_TZ = ZoneInfo("Europe/Moscow")
_OPEN = {
    "day": None,
    "timezone": _TZ,
    "day_end_hour": 6,
    "group_id": None,
    "machine_id": None,
    "technician_id": None,
    "offset": 0,
}


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


def _batches() -> _DynamicBatches:
    return _DynamicBatches()


class _DynamicBatches:
    @staticmethod
    def get(batch_id: str) -> AcceptedBatch | None:
        files = tuple(
            AcceptedPhotoFile(
                index=index,
                content_type="image/jpeg",
                storage_key=f"k-{index}",
            )
            for index in range(10)
        )
        return AcceptedBatch(
            batch_id=batch_id,
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_LATE,
            files=files,
        )


def _queries(store: MemoryReviewStore) -> ReviewQueries:
    return ReviewQueries(_catalog(), store, _batches())


def _put_assignment(
    store: MemoryReviewStore,
    *,
    batch_id: str,
    occurred_at: datetime,
    group_id: str,
    indexes: tuple[int, ...] = (0,),
    machine_id: str = "m-1",
    technician_id: str = "t-1",
) -> None:
    kept = tuple(
        item for item in store.assignments_for_batch(batch_id) if item.group_id != group_id
    )
    store.replace_assignments(
        batch_id,
        (
            *kept,
            GroupAssignment(
                batch_id=batch_id,
                group_id=group_id,
                indexes=indexes,
                machine_id=machine_id,
                technician_id=technician_id,
                occurred_at=occurred_at,
            ),
        ),
        clear_missing_group_ids=(),
    )


def _human_record(
    batch_id: str,
    group_id: str,
    *,
    indexes: tuple[int, ...] = (0,),
    technician_id: str = "t-1",
    machine_id: str = "m-1",
    occurred_at: datetime = _LATE,
) -> ReviewRecord:
    return ReviewRecord(
        batch_id=batch_id,
        group_id=group_id,
        record_kind="human",
        indexes=indexes,
        defects=(DefectMark("dirty", "Грязь"),),
        system_error=False,
        comment="",
        creator_kind="human",
        actor_user_id="user-1",
        saved_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
        group_title="Бак отходов" if group_id == "waste_tank" else "Стакан",
        machine_id=machine_id,
        technician_id=technician_id,
        occurred_at=occurred_at,
    )


def _missing_record(
    batch_id: str,
    group_id: str,
    *,
    technician_id: str = "t-1",
    machine_id: str = "m-1",
    occurred_at: datetime = _LATE,
) -> ReviewRecord:
    return ReviewRecord(
        batch_id=batch_id,
        group_id=group_id,
        record_kind="missing",
        indexes=(),
        defects=(),
        system_error=False,
        comment="",
        creator_kind="system",
        actor_user_id=None,
        saved_at=datetime(2026, 9, 23, 8, 0, tzinfo=UTC),
        group_title="Бак отходов" if group_id == "waste_tank" else "Стакан",
        machine_id=machine_id,
        technician_id=technician_id,
        occurred_at=occurred_at,
    )


def test_list_blocks_uses_operational_day_window() -> None:
    store = MemoryReviewStore()
    early = datetime(2026, 9, 23, 2, 30, tzinfo=UTC)
    late = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
    _put_assignment(store, batch_id="early", occurred_at=early, group_id="waste_tank")
    _put_assignment(store, batch_id="late", occurred_at=late, group_id="waste_tank")
    page = ReviewQueries(_catalog(), store, _batches()).list_blocks(
        day=date(2026, 9, 23),
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        group_id=None,
        machine_id=None,
        technician_id=None,
        offset=0,
    )
    assert [item.batch_id for item in page.items] == ["late"]


def test_list_blocks_page_size_is_50() -> None:
    store = MemoryReviewStore()
    for index in range(51):
        _put_assignment(
            store,
            batch_id=f"b-{index:02d}",
            occurred_at=datetime(2026, 9, 23, 4, 0, tzinfo=UTC),
            group_id="waste_tank",
        )
    page = ReviewQueries(_catalog(), store, _batches()).list_blocks(
        day=None,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        group_id=None,
        machine_id=None,
        technician_id=None,
        offset=0,
    )
    assert len(page.items) == 50
    assert page.total == 51
    assert page.items[0].batch_id == "b-00"


def test_list_blocks_orders_by_catalog_then_time_then_batch() -> None:
    store = MemoryReviewStore()
    later = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    earlier = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
    _put_assignment(store, batch_id="b-2", occurred_at=earlier, group_id="cup")
    _put_assignment(store, batch_id="b-2", occurred_at=earlier, group_id="waste_tank")
    _put_assignment(store, batch_id="b-1", occurred_at=later, group_id="waste_tank")
    page = ReviewQueries(_catalog(), store, _batches()).list_blocks(
        day=None,
        timezone=ZoneInfo("Europe/Moscow"),
        day_end_hour=6,
        group_id=None,
        machine_id=None,
        technician_id=None,
        offset=0,
    )
    assert [(item.group_id, item.batch_id) for item in page.items] == [
        ("waste_tank", "b-2"),
        ("waste_tank", "b-1"),
        ("cup", "b-2"),
    ]


def test_list_blocks_keeps_block_with_human_record() -> None:
    store = MemoryReviewStore()
    _put_assignment(store, batch_id="batch-1", occurred_at=_LATE, group_id="waste_tank")
    store.save_record(_human_record("batch-1", "waste_tank"))
    page = _queries(store).list_blocks(**_OPEN)
    assert page.items[0].has_human_record is True
    assert page.items[0].batch_id == "batch-1"


def test_list_blocks_includes_missing_without_assignment() -> None:
    store = MemoryReviewStore()
    store.save_record(_missing_record("batch-1", "waste_tank"))
    page = _queries(store).list_blocks(**_OPEN)
    assert [(item.batch_id, item.is_missing) for item in page.items] == [("batch-1", True)]
    assert page.items[0].indexes == ()


def test_list_blocks_does_not_invent_missing_from_catalog() -> None:
    store = MemoryReviewStore()
    page = _queries(store).list_blocks(**_OPEN)
    assert page.items == ()
    assert store.list_records() == ()


def test_neighbor_crosses_page_boundary() -> None:
    store = MemoryReviewStore()
    for index in range(51):
        _put_assignment(
            store,
            batch_id=f"b-{index:02d}",
            occurred_at=datetime(2026, 9, 23, 4, 0, tzinfo=UTC),
            group_id="waste_tank",
        )
    neighbor = _queries(store).adjacent_block(
        current_batch_id="b-49",
        current_group_id="waste_tank",
        **_OPEN,
    )
    assert neighbor.next_batch_id == "b-50"
    assert neighbor.prev_batch_id == "b-48"


def test_read_photo_from_assignment_index() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store, batch_id="batch-1", occurred_at=_LATE, group_id="waste_tank", indexes=(0,)
    )
    photo = _queries(store).read_photo("batch-1", 0)
    assert photo is not None
    assert photo.content_type == "image/jpeg"
    assert photo.storage_key == "k-0"
    assert store.list_records() == ()


def test_read_photo_from_record_snapshot_after_assignment_changed() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store, batch_id="batch-1", occurred_at=_LATE, group_id="waste_tank", indexes=(2,)
    )
    store.save_record(_human_record("batch-1", "waste_tank", indexes=(1,)))
    photo = _queries(store).read_photo("batch-1", 1)
    assert photo is not None
    assert photo.storage_key == "k-1"


def test_read_photo_missing_when_index_not_in_assignment_or_record() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store, batch_id="batch-1", occurred_at=_LATE, group_id="waste_tank", indexes=(0,)
    )
    assert _queries(store).read_photo("batch-1", 9) is None
    assert store.list_records() == ()


_QUEUE = {
    "day": None,
    "timezone": _TZ,
    "day_end_hour": 6,
    "machine_id": None,
    "technician_id": None,
}


def test_list_queue_groups_default_unviewed_only() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store,
        batch_id="batch-1",
        occurred_at=_LATE,
        group_id="waste_tank",
        indexes=(0, 1),
    )
    store.save_frame_view(
        FrameView(
            batch_id="batch-1",
            index=0,
            actor_user_id="u-1",
            viewed_at=datetime(2026, 9, 23, 9, 0, tzinfo=UTC),
        )
    )
    groups = _queries(store).list_queue_groups(**_QUEUE)
    assert [item.group_id for item in groups] == ["waste_tank"]
    assert [(frame.batch_id, frame.index) for frame in groups[0].frames] == [("batch-1", 1)]
    assert groups[0].is_missing is False


def test_queue_group_frames_sorted_by_spec_order() -> None:
    store = MemoryReviewStore()
    earlier = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
    later = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    _put_assignment(
        store,
        batch_id="b-2",
        occurred_at=earlier,
        group_id="waste_tank",
        indexes=(1, 0),
    )
    _put_assignment(
        store,
        batch_id="b-1",
        occurred_at=earlier,
        group_id="waste_tank",
        indexes=(0,),
    )
    _put_assignment(
        store,
        batch_id="b-3",
        occurred_at=later,
        group_id="waste_tank",
        indexes=(0,),
    )
    groups = _queries(store).list_queue_groups(**_QUEUE)
    assert len(groups) == 1
    assert [(frame.batch_id, frame.index) for frame in groups[0].frames] == [
        ("b-1", 0),
        ("b-2", 0),
        ("b-2", 1),
        ("b-3", 0),
    ]


def test_list_queue_groups_hides_empty_missing_tile() -> None:
    # happy — ISS-023: zero frames → no review tile
    store = MemoryReviewStore()
    store.save_record(_missing_record("batch-1", "waste_tank"))
    groups = _queries(store).list_queue_groups(**_QUEUE)
    assert groups == ()


def test_list_queue_groups_keeps_group_with_frames() -> None:
    # edge
    store = MemoryReviewStore()
    _put_assignment(
        store,
        batch_id="batch-1",
        occurred_at=_LATE,
        group_id="waste_tank",
        indexes=(0,),
    )
    groups = _queries(store).list_queue_groups(**_QUEUE)
    assert len(groups) == 1
    assert groups[0].group_id == "waste_tank"
    assert groups[0].frames
    assert groups[0].is_missing is False


def test_list_queue_groups_hides_fully_viewed_group() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store,
        batch_id="batch-1",
        occurred_at=_LATE,
        group_id="waste_tank",
        indexes=(0,),
    )
    store.save_frame_view(
        FrameView(
            batch_id="batch-1",
            index=0,
            actor_user_id="u-1",
            viewed_at=datetime(2026, 9, 23, 9, 0, tzinfo=UTC),
        )
    )
    groups = _queries(store).list_queue_groups(**_QUEUE)
    assert groups == ()


def test_list_queue_groups_all_mode_includes_viewed() -> None:
    store = MemoryReviewStore()
    _put_assignment(
        store,
        batch_id="batch-1",
        occurred_at=_LATE,
        group_id="waste_tank",
        indexes=(0, 1),
    )
    store.save_frame_view(
        FrameView(
            batch_id="batch-1",
            index=0,
            actor_user_id="u-1",
            viewed_at=datetime(2026, 9, 23, 9, 0, tzinfo=UTC),
        )
    )
    groups = _queries(store).list_queue_groups(**_QUEUE, view_filter="all")
    assert len(groups) == 1
    assert [(frame.batch_id, frame.index) for frame in groups[0].frames] == [
        ("batch-1", 0),
        ("batch-1", 1),
    ]


def test_list_queue_groups_propagates_catalog_unavailable() -> None:
    store = MemoryReviewStore()
    queries = ReviewQueries(
        FixedCatalog(
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
        ),
        store,
        _batches(),
    )
    with pytest.raises(CatalogUnavailable):
        queries.list_queue_groups(**_QUEUE)


def test_list_catalog_editor_groups_includes_photo_only() -> None:
    catalog = FixedCatalog(
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
                CatalogGroup(
                    group_id="unrecognized",
                    title="Нераспознанное",
                    required=False,
                    defects=(),
                ),
                CatalogGroup(
                    group_id="poor_quality",
                    title="Некачественное фото",
                    required=False,
                    defects=(),
                ),
            )
        )
    )
    rows = ReviewQueries(catalog, MemoryReviewStore(), _batches()).list_catalog_editor_groups()
    assert [row.group_id for row in rows] == [
        "waste_tank",
        "cup",
        "poor_quality",
        "trash",
    ]
    assert [row.photo_only for row in rows] == [False, False, True, True]
    assert rows[0].defects == (DefectButton(code="dirty", label="Грязь"),)
    assert rows[2].title == "Некачественное фото"
    assert rows[3].title == "Мусор"


def test_list_catalog_editor_groups_orders_content_by_title_then_service_rows() -> None:
    catalog = FixedCatalog(
        ReviewCatalog(
            groups=(
                CatalogGroup(group_id="z_last", title="Ящик", required=False, defects=()),
                CatalogGroup(group_id="a_first", title="Аккумулятор", required=True, defects=()),
            )
        )
    )
    rows = ReviewQueries(catalog, MemoryReviewStore(), _batches()).list_catalog_editor_groups()
    assert [row.group_id for row in rows] == [
        "a_first",
        "z_last",
        "poor_quality",
        "trash",
    ]
    assert all(row.photo_only for row in rows[-2:])


def test_list_problem_rows_one_per_defect() -> None:
    store = MemoryReviewStore()
    store.save_record(
        ReviewRecord(
            batch_id="batch-1",
            group_id="waste_tank",
            record_kind="human",
            indexes=(2, 5),
            defects=(
                DefectMark("dirty", "Грязь"),
                DefectMark("empty", "Пусто"),
            ),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="user-1",
            saved_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_LATE,
        )
    )
    result = _queries(store).list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
    )
    assert result.total == 2
    assert [row.defect_code for row in result.items] == ["dirty", "empty"]
    assert all(row.photo_index == 2 for row in result.items)
    assert all(row.batch_id == "batch-1" for row in result.items)
    assert all(row.group_title == "Бак отходов" for row in result.items)


def test_list_problem_rows_skips_missing_and_empty() -> None:
    store = MemoryReviewStore()
    store.save_record(_missing_record("batch-1", "waste_tank"))
    store.save_record(
        ReviewRecord(
            batch_id="batch-2",
            group_id="cup",
            record_kind="human",
            indexes=(0,),
            defects=(),
            system_error=True,
            comment="",
            creator_kind="human",
            actor_user_id="user-1",
            saved_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
            group_title="Стакан",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_LATE,
        )
    )
    store.save_record(_human_record("batch-3", "waste_tank"))
    result = _queries(store).list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
    )
    assert result.total == 1
    assert result.items[0].batch_id == "batch-3"
    assert result.items[0].defect_code == "dirty"


def test_list_problem_rows_default_day_and_sort() -> None:
    store = MemoryReviewStore()
    earlier = datetime(2026, 9, 23, 3, 0, tzinfo=UTC)
    later = datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    store.save_record(_human_record("old", "waste_tank", occurred_at=earlier))
    store.save_record(_human_record("new", "cup", occurred_at=later, indexes=(1,)))
    other_day = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    store.save_record(_human_record("skip", "waste_tank", occurred_at=other_day))
    result = _queries(store).list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
    )
    assert [row.batch_id for row in result.items] == ["new", "old"]


def test_list_problem_rows_column_filters() -> None:
    store = MemoryReviewStore()
    store.save_record(_human_record("b1", "waste_tank", machine_id="m-1", technician_id="t-1"))
    store.save_record(_human_record("b2", "cup", machine_id="m-2", technician_id="t-2"))
    store.save_record(
        ReviewRecord(
            batch_id="b3",
            group_id="waste_tank",
            record_kind="human",
            indexes=(0,),
            defects=(DefectMark("empty", "Пусто"),),
            system_error=False,
            comment="",
            creator_kind="human",
            actor_user_id="user-1",
            saved_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
            group_title="Бак отходов",
            machine_id="m-1",
            technician_id="t-1",
            occurred_at=_LATE,
        )
    )
    q = _queries(store)
    by_machine = q.list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
        machine_id="m-2",
    )
    assert [row.batch_id for row in by_machine.items] == ["b2"]
    by_group = q.list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
        group_id="waste_tank",
    )
    assert {row.batch_id for row in by_group.items} == {"b1", "b3"}
    by_defect = q.list_problem_rows(
        day=date(2026, 9, 23),
        timezone=_TZ,
        day_end_hour=6,
        defect_query="пусто",
    )
    assert [row.batch_id for row in by_defect.items] == ["b3"]


def test_list_problem_rows_page_size_none_returns_every_row() -> None:
    # edge: facet lists must not stop at the table page
    store = MemoryReviewStore()
    for index in range(51):
        store.save_record(_human_record(f"b-{index}", "waste_tank"))
    queries = _queries(store)
    kwargs = {
        "day": date(2026, 9, 23),
        "timezone": _TZ,
        "day_end_hour": 6,
    }
    paged = queries.list_problem_rows(**kwargs)
    assert paged.total == 51
    assert len(paged.items) == 50
    full = queries.list_problem_rows(**kwargs, page_size=None)
    assert len(full.items) == 51


def test_list_problem_rows_invalid_day_empty() -> None:
    store = MemoryReviewStore()
    store.save_record(_human_record("batch-1", "waste_tank"))
    result = _queries(store).list_problem_rows(
        day=None,
        timezone=_TZ,
        day_end_hour=6,
        day_raw="not-a-day",
    )
    assert result.total == 0
    assert result.items == ()
