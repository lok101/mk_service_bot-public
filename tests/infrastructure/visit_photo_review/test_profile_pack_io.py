from __future__ import annotations

from pathlib import Path

from tests.application.visit_photo_review.test_visit_photo_profile import _FakeCatalog

from src.application.visit_photo_review.commands import (
    WriteGroupAvatar,
    WriteGroupAvatarError,
)
from src.application.visit_photo_review.ports import AcceptedBatch, AcceptedPhotoFile
from src.application.visit_photo_review.profile import (
    InMemoryVisitPhotoProfileStore,
    MachineEquipmentFacts,
    ResolveVisitPhotoProfile,
    SaveVisitPhotoProfile,
    VisitPhotoProfile,
    VisitPhotoProfileGroup,
    VisitPhotoProfileMember,
    migrate_checklist_items_to_groups,
    remove_profile_group,
    seed_service_groups,
)
from src.infrastructure.visit_photo_review.group_avatar import PackDirGroupAvatarWriter
from src.infrastructure.visit_photo_review.profile_pack_io import (
    FilesystemProfileGroupReferenceLayout,
    ProfilePackPathResolver,
    ensure_group_reference_dir,
)


class _Batches:
    def __init__(self, batch: AcceptedBatch | None) -> None:
        self._batch = batch

    def get(self, batch_id: str) -> AcceptedBatch | None:
        if self._batch is None or self._batch.batch_id != batch_id:
            return None
        return self._batch


class _Machines:
    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
        return MachineEquipmentFacts(
            machine_id=machine_id,
            kind="coffee",
            model_id="m-g23",
            stand_type_id="st",
        )


def test_pack_dir_for_batch_uses_profile_pack_key(tmp_path: Path) -> None:
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
    from datetime import UTC, datetime

    batch = AcceptedBatch(
        batch_id="b1",
        machine_id="M1",
        technician_id="t1",
        occurred_at=datetime(2026, 10, 21, tzinfo=UTC),
        files=(AcceptedPhotoFile(index=0, content_type="image/jpeg", storage_key="k"),),
    )
    paths = ProfilePackPathResolver(
        packs_root=tmp_path,
        batches=_Batches(batch),
        resolve_profile=ResolveVisitPhotoProfile(store=store, machines=_Machines()),
        profile_strict=True,
        legacy_default_pack_key=None,
        legacy_pack_dir=None,
    )
    assert paths.pack_dir_for_batch("b1") == tmp_path / "g23"


def test_fallback_pack_dir_uses_default_profile_when_packs_root_only(
    tmp_path: Path,
) -> None:
    store = InMemoryVisitPhotoProfileStore()
    store.upsert(
        VisitPhotoProfile(
            profile_id="default",
            name="Default",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)},
            ),
            groups=migrate_checklist_items_to_groups(("1. A",)),
            pack_key="coffee_default",
        ),
    )
    paths = ProfilePackPathResolver(
        packs_root=tmp_path,
        batches=_Batches(None),
        resolve_profile=ResolveVisitPhotoProfile(store=store, machines=_Machines()),
        profile_strict=False,
        legacy_default_pack_key=None,
        legacy_pack_dir=None,
    )
    assert paths.fallback_pack_dir() == tmp_path / "coffee_default"


def test_add_group_creates_empty_reference_dir(tmp_path: Path) -> None:
    store = InMemoryVisitPhotoProfileStore()
    layout = FilesystemProfileGroupReferenceLayout(packs_root=tmp_path)
    cmd = SaveVisitPhotoProfile(
        store=store,
        catalog=_FakeCatalog(),
        reference_layout=layout,
    )
    groups = seed_service_groups() + (
        VisitPhotoProfileGroup(
            group_id="before",
            title="До",
            required=True,
            defects=(),
            photo_only=False,
        ),
    )
    cmd(
        profile_id="p1",
        name="P",
        members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
        groups=groups,
        pack_key="g23",
    )
    ref = tmp_path / "g23" / "reference" / "before"
    assert ref.is_dir()
    assert list(ref.iterdir()) == []


def test_soft_delete_keeps_reference_files(tmp_path: Path) -> None:
    pack = tmp_path / "g23"
    group_dir = ensure_group_reference_dir(pack, "drop-me")
    leftover = group_dir / "avatar.jpg"
    leftover.write_bytes(b"jpeg")
    groups = migrate_checklist_items_to_groups(("Keep", "Drop"))
    # Align id with filesystem folder used above
    groups = tuple(
        VisitPhotoProfileGroup(
            group_id="drop-me" if group.title == "Drop" else group.group_id,
            title=group.title,
            required=group.required,
            defects=group.defects,
            photo_only=group.photo_only,
        )
        for group in groups
    )
    remaining = remove_profile_group(groups, "drop-me")
    assert leftover.is_file()
    assert "drop-me" not in {group.group_id for group in remaining}


def test_avatar_upload_fails_when_pack_missing() -> None:
    writer = PackDirGroupAvatarWriter(pack_dir=None)
    result = WriteGroupAvatar(writer).execute(
        group_id="before",
        content=b"\xff\xd8\xff",
        content_type="image/jpeg",
    )
    assert result.is_err()
    assert result.error is WriteGroupAvatarError.PACK_DIR_UNAVAILABLE
