from __future__ import annotations

import pytest

from src.application.visit_photo_review.profile import (
    CoffeeModelInfo,
    InMemoryVisitPhotoProfileStore,
    MachineEquipmentFacts,
    ProfileCommandRejected,
    ResolveVisitPhotoProfile,
    SaveVisitPhotoProfile,
    VisitPhotoProfile,
    VisitPhotoProfileMember,
)


class _FakeCatalog:
    def __init__(self) -> None:
        self.models: dict[str, CoffeeModelInfo] = {
            "m-g23": CoffeeModelInfo(model_id="m-g23", floor_standing=False),
            "m-jl24": CoffeeModelInfo(model_id="m-jl24", floor_standing=False),
            "m-jl220": CoffeeModelInfo(model_id="m-jl220", floor_standing=True),
            "m-jl300": CoffeeModelInfo(model_id="m-jl300", floor_standing=True),
        }
        self.stand_types: set[str] = {"st-new", "st-old"}

    def model_of(self, model_id: str) -> CoffeeModelInfo | None:
        return self.models.get(model_id)

    def stand_type_exists(self, stand_type_id: str) -> bool:
        return stand_type_id in self.stand_types


class _FakeMachines:
    def __init__(self) -> None:
        self._by: dict[str, MachineEquipmentFacts] = {}

    def put(self, machine_id: str, facts: MachineEquipmentFacts) -> None:
        self._by[machine_id] = facts

    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
        return self._by.get(machine_id)


def _save(
    store: InMemoryVisitPhotoProfileStore,
    catalog: _FakeCatalog,
    *,
    profile_id: str,
    name: str,
    members: frozenset[VisitPhotoProfileMember],
    checklist: tuple[str, ...] = ("1. A", "2. B"),
    pack_key: str = "pack-a",
) -> VisitPhotoProfile:
    cmd = SaveVisitPhotoProfile(store=store, catalog=catalog)
    return cmd(
        profile_id=profile_id,
        name=name,
        members=members,
        checklist_items=checklist,
        pack_key=pack_key,
        technician_reference_keys=(),
    )


def test_save_and_resolve_happy() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    machines = _FakeMachines()
    members = frozenset(
        {
            VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new"),
            VisitPhotoProfileMember(model_id="m-jl24", stand_type_id="st-new"),
        }
    )
    profile = _save(store, catalog, profile_id="p1", name="New G23/JL24", members=members)
    assert profile.photo_count == 2
    assert profile.min_photo_count == 2
    assert profile.max_photo_count == 2

    machines.put(
        "M1",
        MachineEquipmentFacts(
            machine_id="M1",
            kind="coffee",
            model_id="m-g23",
            stand_type_id="st-new",
        ),
    )
    resolved = ResolveVisitPhotoProfile(store=store, machines=machines)("M1")
    assert resolved is not None
    assert resolved.profile_id == "p1"


def test_floor_models_get_distinct_profiles() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    machines = _FakeMachines()
    _save(
        store,
        catalog,
        profile_id="p-jl220",
        name="JL220 floor",
        members=frozenset({VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)}),
        pack_key="jl220",
    )
    _save(
        store,
        catalog,
        profile_id="p-jl300",
        name="JL300 floor",
        members=frozenset({VisitPhotoProfileMember(model_id="m-jl300", stand_type_id=None)}),
        pack_key="jl300",
    )
    machines.put(
        "A",
        MachineEquipmentFacts("A", "coffee", "m-jl220", None),
    )
    machines.put(
        "B",
        MachineEquipmentFacts("B", "coffee", "m-jl300", None),
    )
    resolve = ResolveVisitPhotoProfile(store=store, machines=machines)
    assert resolve("A").profile_id == "p-jl220"  # type: ignore[union-attr]
    assert resolve("B").profile_id == "p-jl300"  # type: ignore[union-attr]


def test_member_overlap_rejected() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    member = VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")
    _save(store, catalog, profile_id="p1", name="One", members=frozenset({member}))
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(store, catalog, profile_id="p2", name="Two", members=frozenset({member}))
    assert exc.value.code == "profile_member_overlap"


def test_empty_checklist_rejected() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(
            store,
            catalog,
            profile_id="p1",
            name="Empty",
            members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id="st-new")}),
            checklist=(),
        )
    assert exc.value.code == "checklist_empty"


def test_stand_on_floor_model_rejected() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(
            store,
            catalog,
            profile_id="p1",
            name="Bad floor",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id="st-new")}
            ),
        )
    assert exc.value.code == "stand_not_allowed_for_floor_model"


def test_non_floor_requires_stand() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(
            store,
            catalog,
            profile_id="p1",
            name="Missing stand",
            members=frozenset({VisitPhotoProfileMember(model_id="m-g23", stand_type_id=None)}),
        )
    assert exc.value.code == "stand_required"


def test_unknown_catalog_rejected() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(
            store,
            catalog,
            profile_id="p1",
            name="Unknown",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-missing", stand_type_id="st-new")}
            ),
        )
    assert exc.value.code == "unknown_catalog_entry"


def test_resolve_miss_when_no_match() -> None:
    store = InMemoryVisitPhotoProfileStore()
    machines = _FakeMachines()
    machines.put(
        "M1",
        MachineEquipmentFacts("M1", "coffee", "m-g23", "st-new"),
    )
    assert ResolveVisitPhotoProfile(store=store, machines=machines)("M1") is None


def test_save_rejects_traversal_pack_key() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    with pytest.raises(ProfileCommandRejected) as exc:
        _save(
            store,
            catalog,
            profile_id="p1",
            name="Bad pack",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)},
            ),
            pack_key="../other",
        )
    assert exc.value.code == "pack_key_invalid"


def test_default_profile_fallback() -> None:
    store = InMemoryVisitPhotoProfileStore()
    catalog = _FakeCatalog()
    default = _save(
        store,
        catalog,
        profile_id="default",
        name="Default",
        members=frozenset(
            {VisitPhotoProfileMember(model_id="m-jl220", stand_type_id=None)},
        ),
        pack_key="default_pack",
    )
    machines = _FakeMachines()
    machines.put(
        "M1",
        MachineEquipmentFacts("M1", "coffee", "m-g23", "st-new"),
    )
    resolve = ResolveVisitPhotoProfile(store=store, machines=machines)
    assert resolve("M1") is None
    assert resolve.default_profile() == default
