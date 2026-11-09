from __future__ import annotations

from pathlib import Path

from src.application.visit_photo_grouping.group_accepted_batch import GroupingRetryReason
from src.application.visit_photo_grouping.ports import (
    GroupingStoredFile,
    GroupingSuccess,
    GroupingTemporaryFailure,
)
from src.application.visit_photo_review.profile import (
    InMemoryVisitPhotoProfileStore,
    MachineEquipmentFacts,
    ResolveVisitPhotoProfile,
    VisitPhotoProfile,
    VisitPhotoProfileMember,
    migrate_checklist_items_to_groups,
)
from src.infrastructure.visit_photo_grouping.openclip_classifier import (
    OpenClipGroupClassifier,
)
from src.infrastructure.visit_photo_grouping.profile_aware_classifier import (
    ProfileAwareGroupClassifier,
)


class _Machines:
    def __init__(self, facts: MachineEquipmentFacts) -> None:
        self._facts = facts

    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
        if machine_id == self._facts.machine_id:
            return self._facts
        return None


class _FakeOpenClip:
    def __init__(self, pack_dir: Path) -> None:
        self.pack_dir = pack_dir

    def classify(
        self,
        batch_id: str,
        files: tuple[GroupingStoredFile, ...],
    ) -> GroupingSuccess:
        return GroupingSuccess(groups=())


def test_profile_aware_uses_pack_key(tmp_path: Path) -> None:
    pack = tmp_path / "g23"
    pack.mkdir()
    store = InMemoryVisitPhotoProfileStore()
    store.upsert(
        VisitPhotoProfile(
            profile_id="p1",
            name="G23",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st")},
            ),
            groups=migrate_checklist_items_to_groups(("1. A",)),
            pack_key="g23",
        ),
    )
    resolve = ResolveVisitPhotoProfile(
        store=store,
        machines=_Machines(
            MachineEquipmentFacts(
                machine_id="M1",
                kind="coffee",
                model_id="m-g23",
                stand_type_id="st",
            ),
        ),
    )
    built: list[Path] = []

    def _build(path: Path) -> OpenClipGroupClassifier:
        built.append(path)
        return _FakeOpenClip(path)  # type: ignore[return-value]

    classifier = ProfileAwareGroupClassifier(
        packs_root=tmp_path,
        machine_id_for_batch=lambda _bid: "M1",
        resolve_profile=resolve,
        profile_strict=True,
        legacy_default_pack_key=None,
        build_classifier=_build,
    )
    result = classifier.classify("b1", ())
    assert isinstance(result, GroupingSuccess)
    assert built == [pack]


def test_profile_aware_strict_miss(tmp_path: Path) -> None:
    resolve = ResolveVisitPhotoProfile(
        store=InMemoryVisitPhotoProfileStore(),
        machines=_Machines(
            MachineEquipmentFacts(
                machine_id="M1",
                kind="coffee",
                model_id="m-g23",
                stand_type_id="st",
            ),
        ),
    )
    classifier = ProfileAwareGroupClassifier(
        packs_root=tmp_path,
        machine_id_for_batch=lambda _bid: "M1",
        resolve_profile=resolve,
        profile_strict=True,
        legacy_default_pack_key=None,
        build_classifier=lambda path: _FakeOpenClip(path),  # type: ignore[arg-type,return-value]
    )
    result = classifier.classify("b1", ())
    assert isinstance(result, GroupingTemporaryFailure)
    assert result.reason_code == GroupingRetryReason.VISIT_PHOTO_PROFILE_MISSING.value
