from __future__ import annotations

from src.application.visit_photo_review.profile import (
    InMemoryVisitPhotoProfileStore,
    MachineEquipmentFacts,
    ResolveVisitPhotoProfile,
    VisitPhotoProfile,
    VisitPhotoProfileMember,
    migrate_checklist_items_to_groups,
)
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    ResolveVisitPhotoProfileCueAdapter,
)

_COFFEE_ITEMS = ("1. Общий план ДО.", "2. Органайзер.")


class _Machines:
    def __init__(self) -> None:
        self._by: dict[str, MachineEquipmentFacts] = {}

    def put(self, facts: MachineEquipmentFacts) -> None:
        self._by[facts.machine_id] = facts

    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
        return self._by.get(machine_id)


def _adapter(machines: _Machines) -> ResolveVisitPhotoProfileCueAdapter:
    store = InMemoryVisitPhotoProfileStore()
    store.upsert(
        VisitPhotoProfile(
            profile_id="default",
            name="Кофе",
            members=frozenset(
                {VisitPhotoProfileMember(model_id="m-floor", stand_type_id=None)},
            ),
            groups=migrate_checklist_items_to_groups(_COFFEE_ITEMS),
            pack_key="coffee-pack",
        )
    )
    resolve = ResolveVisitPhotoProfile(store=store, machines=machines)
    return ResolveVisitPhotoProfileCueAdapter(resolve=resolve, profile_strict=False)


def test_coffee_membership_miss_uses_default_profile() -> None:
    machines = _Machines()
    machines.put(MachineEquipmentFacts("M1", "coffee", "m-g23", "st-new"))
    cue = _adapter(machines).cue_for("M1")
    assert cue is not None
    assert cue.checklist_items == _COFFEE_ITEMS


def test_snack_does_not_receive_coffee_default_profile() -> None:
    machines = _Machines()
    machines.put(MachineEquipmentFacts("S1", "snack", None, None))
    assert _adapter(machines).cue_for("S1") is None
