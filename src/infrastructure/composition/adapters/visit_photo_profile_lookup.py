from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.master_data import CoffeeMachineModelStore, StandTypeStore
from src.application.master_data.ports import MasterMachineStore
from src.application.photo_batches.loading_photos_limits import LoadingPhotosProfileCue
from src.application.visit_photo_review.profile import (
    CoffeeModelInfo,
    MachineEquipmentFacts,
    ResolveVisitPhotoProfile,
    VisitPhotoProfile,
)
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class MasterCoffeeEquipmentCatalogLookup:
    """Adapts coffee model/stand stores to CoffeeEquipmentCatalogLookup."""

    models: CoffeeMachineModelStore
    stand_types: StandTypeStore

    def model_of(self, model_id: str) -> CoffeeModelInfo | None:
        model = self.models.get(model_id)
        if model is None:
            return None
        return CoffeeModelInfo(model_id=model.model_id, floor_standing=model.floor_standing)

    def stand_type_exists(self, stand_type_id: str) -> bool:
        return self.stand_types.get(stand_type_id) is not None


@beartype
@dataclass(frozen=True, slots=True)
class MasterMachineEquipmentLookup:
    """Reads coffee model/stand facts from master_data for profile resolve."""

    _machines: MasterMachineStore

    def equipment_of(self, machine_id: str) -> MachineEquipmentFacts | None:
        machine = self._machines.get(MachineId(machine_id))
        if machine is None:
            return None
        return MachineEquipmentFacts(
            machine_id=machine_id,
            kind=str(machine.kind),
            model_id=machine.coffee_machine_model_id,
            stand_type_id=machine.stand_type_id,
        )


@beartype
@dataclass(frozen=True, slots=True)
class ResolveVisitPhotoProfileCueAdapter:
    """Adapts ResolveVisitPhotoProfile to LoadingPhotosProfileLookup."""

    resolve: ResolveVisitPhotoProfile
    profile_strict: bool = False

    def cue_for(self, machine_code: str) -> LoadingPhotosProfileCue | None:
        profile: VisitPhotoProfile | None = self.resolve(machine_code)
        if (
            profile is None
            and not self.profile_strict
            and _equipment_kind_is_coffee(self.resolve, machine_code)
        ):
            profile = self.resolve.default_profile()
        if profile is None:
            return None
        return LoadingPhotosProfileCue(
            min_count=profile.min_photo_count,
            max_count=profile.max_photo_count,
            checklist_items=profile.checklist_items,
        )


@beartype
def _equipment_kind_is_coffee(resolve: ResolveVisitPhotoProfile, machine_code: str) -> bool:
    facts = resolve.machines.equipment_of(machine_code)
    return facts is not None and facts.kind == "coffee"
