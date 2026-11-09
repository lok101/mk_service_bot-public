from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.application.visit_photo_review.fakes import (
    FixedBatches,
    FixedCatalog,
    FixedClock,
    MemoryReviewStore,
)

from src.application.visit_photo_grouping import GroupAcceptedBatch, GroupingRetryReason
from src.application.visit_photo_grouping.group_accepted_batch import DeliveryKind
from src.application.visit_photo_grouping.ports import (
    GroupingBatchView,
    GroupingGroup,
    GroupingPermanentFailure,
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
)
from src.application.visit_photo_review import AssignBatchGroups, RecordMissingRequiredGroup
from src.application.visit_photo_review.ports import AcceptedBatch, AcceptedPhotoFile
from src.domain.visit_photo_review import (
    CatalogGroup,
    DefectMark,
    GroupAssignment,
    ReviewCatalog,
    ReviewRecord,
)

_OCCURRED = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
_UNSET = object()


def _catalog_groups() -> ReviewCatalog:
    return ReviewCatalog(
        groups=(
            CatalogGroup(group_id="waste_tank", title="Бак", required=True, defects=()),
            CatalogGroup(group_id="cup", title="Стакан", required=True, defects=()),
            CatalogGroup(group_id="front", title="Фасад", required=True, defects=()),
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


def _review_batch() -> AcceptedBatch:
    return AcceptedBatch(
        batch_id="batch-1",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED,
        files=(
            AcceptedPhotoFile(index=0, content_type="image/jpeg", storage_key="k0"),
            AcceptedPhotoFile(index=1, content_type="image/jpeg", storage_key="k1"),
        ),
    )


def _grouping_batch(
    status: str = "accepted",
    hashes: tuple[str, str] = ("h0", "h1"),
) -> GroupingBatchView:
    return GroupingBatchView(
        batch_id="batch-1",
        machine_id="m-1",
        status=status,
        files=(
            GroupingStoredFile(
                index=0,
                storage_key="k0",
                content_type="image/jpeg",
                content_hash=hashes[0],
            ),
            GroupingStoredFile(
                index=1,
                storage_key="k1",
                content_type="image/jpeg",
                content_hash=hashes[1],
            ),
        ),
    )


def _human(group_id: str) -> ReviewRecord:
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
        group_title="Стакан",
        machine_id="m-1",
        technician_id="t-1",
        occurred_at=_OCCURRED,
    )


class RecordingStore(MemoryReviewStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def replace_assignments(
        self,
        batch_id: str,
        assignments: tuple[GroupAssignment, ...],
        *,
        clear_missing_group_ids: tuple[str, ...],
    ) -> None:
        self.calls.append("replace")
        super().replace_assignments(
            batch_id,
            assignments,
            clear_missing_group_ids=clear_missing_group_ids,
        )

    def save_record(self, record: ReviewRecord) -> None:
        self.calls.append(f"save:{record.group_id}")
        super().save_record(record)


class FixedGroupingBatches:
    def __init__(self, batch: GroupingBatchView | None) -> None:
        self._batch = batch

    def get(self, batch_id: str) -> GroupingBatchView | None:
        if self._batch is None or self._batch.batch_id != batch_id:
            return None
        return self._batch


class FixedParticipation:
    def __init__(self, included: bool) -> None:
        self._included = included

    def include(self, machine_id: str) -> bool:
        return self._included


class FixedClassifier:
    def __init__(
        self,
        result: GroupingSuccess | GroupingTemporaryFailure | GroupingPermanentFailure,
    ) -> None:
        self._result = result
        self.calls = 0

    def classify(
        self,
        batch_id: str,
        files: tuple[GroupingStoredFile, ...],
    ) -> GroupingSuccess | GroupingTemporaryFailure | GroupingPermanentFailure:
        self.calls += 1
        return self._result


def _subject(
    store: RecordingStore,
    classifier: FixedClassifier,
    *,
    batch: GroupingBatchView | None | object = _UNSET,
    included: bool = True,
    review_batches: FixedBatches | None = None,
    use_catalog: object | None = None,
    command_catalog: object | None = None,
    clock: FixedClock | None = None,
) -> tuple[GroupAcceptedBatch, FixedClock]:
    loaded = use_catalog or FixedCatalog(_catalog_groups())
    commands = command_catalog or loaded
    batches = review_batches if review_batches is not None else FixedBatches(_review_batch())
    clock = clock or FixedClock(_OCCURRED)
    seen = _grouping_batch() if batch is _UNSET else batch
    use_case = GroupAcceptedBatch(
        batches=FixedGroupingBatches(seen),  # type: ignore[arg-type]
        participation=FixedParticipation(included),
        classifier=classifier,
        catalog=loaded,
        assign=AssignBatchGroups(commands, store, batches),
        missing=RecordMissingRequiredGroup(commands, store, batches, clock.now),
    )
    return use_case, clock


def test_group_two_indexes_then_missing_required() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0, 1)),)))
    use_case, _clock = _subject(store, classifier)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert store.calls == ["replace", "save:cup", "save:front"]
    assignment = store.find_assignment("batch-1", "waste_tank")
    assert assignment is not None
    assert assignment.indexes == (0, 1)
    assert store.find_record("batch-1", "cup") is not None
    assert store.find_record("batch-1", "cup").record_kind == "missing"
    assert store.find_record("batch-1", "front") is not None
    assert store.find_assignment("batch-1", "cup") is None


def test_group_empty_success_assigns_all_to_unrecognized() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=()))
    use_case, _clock = _subject(store, classifier)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert store.calls == ["replace"]
    assignment = store.find_assignment("batch-1", "unrecognized")
    assert assignment is not None
    assert assignment.indexes == (0, 1)
    assert store.find_record("batch-1", "waste_tank") is None


def test_group_skips_commands_when_machine_excluded() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)),)))
    use_case, _clock = _subject(store, classifier, included=False)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert classifier.calls == 0
    assert store.calls == []


def test_group_skips_commands_when_not_accepted() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)),)))
    pending = _grouping_batch(status="pending")
    use_case, _clock = _subject(store, classifier, batch=pending)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert classifier.calls == 0
    assert store.calls == []


def test_group_retries_when_files_not_ready() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=()))
    empty = GroupingBatchView(
        batch_id="batch-1",
        machine_id="m-1",
        status="accepted",
        files=(),
    )
    missing_hash = _grouping_batch(hashes=("", "h1"))
    for batch in (empty, missing_hash):
        use_case, _clock = _subject(store, classifier, batch=batch)
        delivery = use_case.execute("batch-1")
        assert delivery.kind is DeliveryKind.RETRY
        assert delivery.reason is GroupingRetryReason.BATCH_WAITING_HASHES
    assert classifier.calls == 0
    assert store.calls == []


def test_group_retries_batch_missing_with_reason() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=()))
    use_case, _clock = _subject(store, classifier, batch=None)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.RETRY
    assert delivery.reason is GroupingRetryReason.BATCH_MISSING
    assert delivery.batch_id == "batch-1"
    assert delivery.machine_id == ""
    assert classifier.calls == 0
    assert store.calls == []


def test_group_retries_catalog_unavailable_with_reason() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=()))
    broken = FixedCatalog(_catalog_groups(), unavailable=True)
    use_case, _clock = _subject(store, classifier, use_catalog=broken, command_catalog=broken)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.RETRY
    assert delivery.reason is GroupingRetryReason.CATALOG_UNAVAILABLE
    assert classifier.calls == 0
    assert store.calls == []


def test_group_retries_classifier_temporary_with_reason() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingTemporaryFailure())
    use_case, _clock = _subject(store, classifier)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.RETRY
    assert delivery.reason is GroupingRetryReason.CLASSIFIER_TEMPORARY
    assert store.calls == []


def test_group_retries_assign_catalog_unavailable_with_reason() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0, 1)),)))
    use_catalog = FixedCatalog(_catalog_groups())
    command_catalog = FixedCatalog(_catalog_groups(), unavailable=True)
    use_case, _clock = _subject(
        store,
        classifier,
        use_catalog=use_catalog,
        command_catalog=command_catalog,
    )
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.RETRY
    assert delivery.reason is GroupingRetryReason.ASSIGN_CATALOG_UNAVAILABLE
    assert store.calls == []


def test_group_repeat_keeps_missing_record() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0, 1)),)))
    clock = FixedClock(_OCCURRED)
    use_case, clock = _subject(store, classifier, clock=clock)
    first = use_case.execute("batch-1")
    assert first.kind is DeliveryKind.SUCCESS
    saved_at = store.find_record("batch-1", "cup").saved_at
    clock.now_value = datetime(2026, 9, 23, 13, 0, tzinfo=UTC)
    second = use_case.execute("batch-1")
    assert second.kind is DeliveryKind.SUCCESS
    assert store.find_record("batch-1", "cup").saved_at == saved_at
    assert store.find_record("batch-1", "cup").creator_kind == "system"


def test_group_partial_leaves_unrecognized_without_missing() -> None:
    store = RecordingStore()
    human = _human("cup")
    store.save_record(human)
    store.calls.clear()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)),)))
    use_case, _clock = _subject(store, classifier)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert store.find_record("batch-1", "cup") == human
    assert store.find_assignment("batch-1", "unrecognized") is not None
    assert store.find_assignment("batch-1", "unrecognized").indexes == (1,)
    assert store.find_record("batch-1", "front") is None


def test_group_omitted_indexes_go_to_unrecognized_without_missing() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)),)))
    use_case, _clock = _subject(store, classifier)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assert "save:" not in "".join(store.calls)
    assert store.find_assignment("batch-1", "waste_tank").indexes == (0,)
    assert store.find_assignment("batch-1", "unrecognized").indexes == (1,)


def test_group_response_with_reserved_group_is_permanent() -> None:
    store = RecordingStore()
    for group_id in ("unrecognized", "poor_quality"):
        store.calls.clear()
        classifier = FixedClassifier(
            GroupingSuccess(
                groups=(GroupingGroup(group_id, (0,)), GroupingGroup("waste_tank", (1,)))
            )
        )
        use_case, _clock = _subject(store, classifier)
        delivery = use_case.execute("batch-1")
        assert delivery.kind is DeliveryKind.PERMANENT
        assert store.calls == []


def test_group_catalog_without_reserved_retries() -> None:
    store = RecordingStore()
    thin = ReviewCatalog(
        groups=(CatalogGroup(group_id="waste_tank", title="Бак", required=True, defects=()),)
    )
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0, 1)),)))
    use_case, _clock = _subject(store, classifier, use_catalog=FixedCatalog(thin))
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.RETRY
    assert delivery.reason is GroupingRetryReason.CATALOG_INVALID
    assert classifier.calls == 0
    assert store.calls == []


def test_group_invalid_response_does_not_write() -> None:
    store = RecordingStore()
    samples = (
        GroupingSuccess(groups=(GroupingGroup("unknown", (0,)),)),
        GroupingSuccess(groups=(GroupingGroup("waste_tank", ()),)),
        GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)), GroupingGroup("cup", (0,)))),
        GroupingSuccess(groups=(GroupingGroup("waste_tank", (9,)),)),
    )
    for sample in samples:
        store.calls.clear()
        classifier = FixedClassifier(sample)
        use_case, _clock = _subject(store, classifier)
        delivery = use_case.execute("batch-1")
        assert delivery.kind is DeliveryKind.PERMANENT
        assert store.calls == []
        assert store.assignments_for_batch("batch-1") == ()
        assert store.records_for_batch("batch-1") == ()


def test_group_assign_refusal_does_not_write_missing() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0,)),)))
    use_case, _clock = _subject(store, classifier, review_batches=FixedBatches(None))
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.PERMANENT
    assert store.calls == []
    assert store.records_for_batch("batch-1") == ()


def test_group_permanent_classifier_does_not_write() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingPermanentFailure())
    use_case, _clock = _subject(store, classifier)
    assert use_case.execute("batch-1").kind is DeliveryKind.PERMANENT
    assert store.calls == []


def test_group_temporary_classifier_retries() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingTemporaryFailure())
    use_case, _clock = _subject(store, classifier)
    assert use_case.execute("batch-1").kind is DeliveryKind.RETRY
    assert store.calls == []


def test_group_catalog_unavailable_retries_before_classifier() -> None:
    store = RecordingStore()
    classifier = FixedClassifier(GroupingSuccess(groups=()))
    broken = FixedCatalog(_catalog_groups(), unavailable=True)
    use_case, _clock = _subject(store, classifier, use_catalog=broken, command_catalog=broken)
    assert use_case.execute("batch-1").kind is DeliveryKind.RETRY
    assert classifier.calls == 0
    assert store.calls == []


def test_group_other_missing_error_keeps_assignment() -> None:
    store = RecordingStore()
    use_groups = _catalog_groups()
    command_groups = ReviewCatalog(
        groups=tuple(
            CatalogGroup(
                group_id=item.group_id,
                title=item.title,
                required=item.group_id == "waste_tank",
                defects=(),
            )
            for item in use_groups.groups
        )
    )
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("waste_tank", (0, 1)),)))
    use_case, _clock = _subject(
        store,
        classifier,
        use_catalog=FixedCatalog(use_groups),
        command_catalog=FixedCatalog(command_groups),
    )
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.PERMANENT
    assert store.find_assignment("batch-1", "waste_tank") is not None
    assert store.find_record("batch-1", "cup") is None
    assert store.find_record("batch-1", "front") is None


def test_loading_accept_sources_do_not_reference_visit_photo_grouping() -> None:
    roots = (
        Path("src/application/photo_batches"),
        Path("src/application/form_submissions"),
        Path("src/interfaces/telegram"),
    )
    for root in roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "visit_photo_grouping" not in text, path.as_posix()


def test_grouping_package_does_not_import_photo_batches_or_master_data() -> None:
    root = Path("src/application/visit_photo_grouping")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "photo_batches" not in text, path.as_posix()
        assert "master_data" not in text, path.as_posix()
        assert "form_submissions" not in text, path.as_posix()


def test_handler_id_is_visit_photo_grouping() -> None:
    from src.application.outbox.handler_ids import (
        VISIT_PHOTO_GROUPING_HANDLER_ID as catalog_id,
    )
    from src.application.visit_photo_grouping import VISIT_PHOTO_GROUPING_HANDLER_ID

    assert VISIT_PHOTO_GROUPING_HANDLER_ID == "visit_photo_grouping"
    assert catalog_id == VISIT_PHOTO_GROUPING_HANDLER_ID


def test_grouping_catalog_from_resolved_profile() -> None:
    from src.application.visit_photo_review.profile import (
        InMemoryVisitPhotoProfileStore,
        MachineEquipmentFacts,
        ResolveVisitPhotoProfile,
        VisitPhotoProfile,
        VisitPhotoProfileGroup,
        VisitPhotoProfileMember,
        seed_service_groups,
    )
    from src.infrastructure.visit_photo_review.profile_catalog_source import (
        ProfilePreferringReviewCatalog,
    )

    store = RecordingStore()
    profile_store = InMemoryVisitPhotoProfileStore()
    profile_store.upsert(
        VisitPhotoProfile(
            profile_id="p1",
            name="G23",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st")},
            ),
            groups=seed_service_groups()
            + (
                VisitPhotoProfileGroup(
                    group_id="before",
                    title="До",
                    required=True,
                    defects=(),
                    photo_only=False,
                ),
            ),
            pack_key="g23",
        )
    )

    class _Machines:
        def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
            if machine_id != "m-1":
                return None
            return MachineEquipmentFacts(
                machine_id="m-1",
                kind="coffee",
                model_id="m-g23",
                stand_type_id="st",
            )

    resolve = ResolveVisitPhotoProfile(store=profile_store, machines=_Machines())
    # Shared file catalog lacks profile group_id «before» — must resolve from profile.
    catalog = ProfilePreferringReviewCatalog(
        FixedCatalog(_catalog_groups()),
        resolve,
        profile_strict=False,
    )
    classifier = FixedClassifier(GroupingSuccess(groups=(GroupingGroup("before", (0, 1)),)))
    use_case, _clock = _subject(store, classifier, use_catalog=catalog, command_catalog=catalog)
    delivery = use_case.execute("batch-1")
    assert delivery.kind is DeliveryKind.SUCCESS
    assignment = store.find_assignment("batch-1", "before")
    assert assignment is not None
    assert assignment.indexes == (0, 1)
