from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import uuid4

from beartype import beartype

from src.application.master_data.coffee_equipment import (
    CoffeeEquipmentCatalogs,
    apply_equipment_to_machine,
)
from src.application.master_data.location_address import (
    compose_location_display_name,
    location_address_parts_complete,
)
from src.application.master_data.models import (
    MachineKind,
    MachineStatus,
    MasterDataAuditRecord,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
    allocate_location_id,
    allocate_machine_id,
)
from src.application.master_data.ports import MasterDataStores
from src.domain.ids import MachineId

_LOGGER = logging.getLogger(__name__)


class MasterDataCommandRejected(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@runtime_checkable
class MasterDataExportHook(Protocol):
    def export_all(self, stores: MasterDataStores) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class InstallMachineAtLocationInput:
    name: str
    city: str
    street: str
    house: str
    latitude: Decimal | None
    longitude: Decimal | None
    kind: MachineKind
    actor_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class InstallMachineAtLocationResult:
    location_id: str
    machine_id: MachineId
    placement_id: str


@beartype
def _validate_coordinates(latitude: Decimal | None, longitude: Decimal | None) -> None:
    if latitude is None and longitude is None:
        return
    if latitude is None or longitude is None:
        raise MasterDataCommandRejected(
            "latitude and longitude must both be set or both be None",
            code="InvalidCoordinates",
        )
    if not Decimal("-90") <= latitude <= Decimal("90"):
        raise MasterDataCommandRejected(
            f"latitude {latitude} out of range [-90, 90]",
            code="InvalidCoordinates",
        )
    if not Decimal("-180") <= longitude <= Decimal("180"):
        raise MasterDataCommandRejected(
            f"longitude {longitude} out of range [-180, 180]",
            code="InvalidCoordinates",
        )


@beartype
def _require_location_address_parts(
    *,
    name: str,
    city: str,
    street: str,
    house: str,
) -> tuple[str, str, str, str, str]:
    stripped_name = name.strip()
    stripped_city = city.strip()
    stripped_street = street.strip()
    stripped_house = house.strip()
    if not location_address_parts_complete(
        name=stripped_name,
        city=stripped_city,
        street=stripped_street,
        house=stripped_house,
    ):
        raise MasterDataCommandRejected(
            "location address parts name/city/street/house are required",
            code="IncompleteLocationAddress",
        )
    display_name = compose_location_display_name(
        name=stripped_name,
        street=stripped_street,
        house=stripped_house,
    )
    return stripped_name, stripped_city, stripped_street, stripped_house, display_name


@beartype
def _build_location(
    *,
    location_id: str,
    name: str,
    city: str,
    street: str,
    house: str,
    latitude: Decimal | None,
    longitude: Decimal | None,
) -> MasterLocation:
    (
        stripped_name,
        stripped_city,
        stripped_street,
        stripped_house,
        display_name,
    ) = _require_location_address_parts(
        name=name,
        city=city,
        street=street,
        house=house,
    )
    return MasterLocation(
        location_id=location_id,
        name=stripped_name,
        city=stripped_city,
        street=stripped_street,
        house=stripped_house,
        display_name=display_name,
        latitude=latitude,
        longitude=longitude,
    )


@beartype
def run_master_data_sheets_export(
    export_hook: MasterDataExportHook | None,
    stores: MasterDataStores,
) -> None:
    if export_hook is None:
        return
    try:
        export_hook.export_all(stores)
    except Exception:
        _LOGGER.exception("master_data sheets export failed; domain change kept")


@beartype
def _append_audit(
    stores: MasterDataStores,
    *,
    at: datetime,
    actor_telegram_user_id: int,
    command: str,
    payload: dict[str, str],
) -> None:
    stores.audit.append(
        MasterDataAuditRecord(
            at=at,
            actor_telegram_user_id=actor_telegram_user_id,
            command=command,
            payload=payload,
        )
    )


@beartype
@dataclass(slots=True)
class InstallMachineAtLocation:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    export_hook: MasterDataExportHook | None = None

    @beartype
    def execute(self, input: InstallMachineAtLocationInput) -> InstallMachineAtLocationResult:
        _validate_coordinates(input.latitude, input.longitude)
        now = self.now_factory()
        location_id = allocate_location_id(self.stores.counters)
        location = _build_location(
            location_id=location_id,
            name=input.name,
            city=input.city,
            street=input.street,
            house=input.house,
            latitude=input.latitude,
            longitude=input.longitude,
        )
        self.stores.locations.upsert(location)
        machine_id = allocate_machine_id(self.stores.counters, input.kind)
        self.stores.machines.upsert(
            MasterMachine(
                machine_id=machine_id,
                kind=input.kind,
                status=MachineStatus.ACTIVE_ON_SITE,
                label=None,
            )
        )
        placement_id = str(uuid4())
        self.stores.placements.insert(
            MasterPlacement(
                placement_id=placement_id,
                machine_id=machine_id,
                location_id=location_id,
                valid_from=now,
                valid_to=None,
            )
        )
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="InstallMachineAtLocation",
            payload={
                "location_id": location_id,
                "machine_id": machine_id.value,
                "placement_id": placement_id,
                "name": location.name,
                "city": location.city,
                "street": location.street,
                "house": location.house,
                "display_name": location.display_name,
            },
        )
        run_master_data_sheets_export(self.export_hook, self.stores)
        return InstallMachineAtLocationResult(
            location_id=location_id,
            machine_id=machine_id,
            placement_id=placement_id,
        )


@beartype
@dataclass(frozen=True, slots=True)
class RelocateMachineInput:
    machine_id: MachineId
    name: str
    city: str
    street: str
    house: str
    latitude: Decimal | None
    longitude: Decimal | None
    actor_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class RelocateMachineResult:
    location_id: str
    machine_id: MachineId
    placement_id: str


@beartype
@dataclass(slots=True)
class RelocateMachine:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    export_hook: MasterDataExportHook | None = None

    @beartype
    def execute(self, input: RelocateMachineInput) -> RelocateMachineResult:
        _validate_coordinates(input.latitude, input.longitude)
        open_placement = self.stores.placements.get_open(input.machine_id)
        if open_placement is None:
            raise MasterDataCommandRejected(
                f"no open placement for machine {input.machine_id.value!r}",
                code="NoOpenPlacement",
            )
        now = self.now_factory()
        location_id = allocate_location_id(self.stores.counters)
        location = _build_location(
            location_id=location_id,
            name=input.name,
            city=input.city,
            street=input.street,
            house=input.house,
            latitude=input.latitude,
            longitude=input.longitude,
        )
        self.stores.locations.upsert(location)
        self.stores.placements.update(
            MasterPlacement(
                placement_id=open_placement.placement_id,
                machine_id=open_placement.machine_id,
                location_id=open_placement.location_id,
                valid_from=open_placement.valid_from,
                valid_to=now,
            )
        )
        placement_id = str(uuid4())
        self.stores.placements.insert(
            MasterPlacement(
                placement_id=placement_id,
                machine_id=input.machine_id,
                location_id=location_id,
                valid_from=now,
                valid_to=None,
            )
        )
        machine = self.stores.machines.get(input.machine_id)
        if machine is not None and machine.status is not MachineStatus.ACTIVE_ON_SITE:
            self.stores.machines.upsert(replace(machine, status=MachineStatus.ACTIVE_ON_SITE))
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="RelocateMachine",
            payload={
                "location_id": location_id,
                "machine_id": input.machine_id.value,
                "placement_id": placement_id,
                "name": location.name,
                "city": location.city,
                "street": location.street,
                "house": location.house,
                "display_name": location.display_name,
            },
        )
        run_master_data_sheets_export(self.export_hook, self.stores)
        return RelocateMachineResult(
            location_id=location_id,
            machine_id=input.machine_id,
            placement_id=placement_id,
        )


@beartype
@dataclass(frozen=True, slots=True)
class UpdateLocationAttributesInput:
    location_id: str
    name: str
    city: str
    street: str
    house: str
    latitude: Decimal | None
    longitude: Decimal | None
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class UpdateLocationAttributes:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    export_hook: MasterDataExportHook | None = None

    @beartype
    def execute(self, input: UpdateLocationAttributesInput) -> None:
        _validate_coordinates(input.latitude, input.longitude)
        existing = self.stores.locations.get(input.location_id)
        if existing is None:
            raise MasterDataCommandRejected(
                f"unknown location_id {input.location_id!r}",
                code="UnknownLocation",
            )
        now = self.now_factory()
        location = _build_location(
            location_id=input.location_id,
            name=input.name,
            city=input.city,
            street=input.street,
            house=input.house,
            latitude=input.latitude,
            longitude=input.longitude,
        )
        self.stores.locations.upsert(location)
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="UpdateLocationAttributes",
            payload={
                "location_id": input.location_id,
                "name": location.name,
                "city": location.city,
                "street": location.street,
                "house": location.house,
                "display_name": location.display_name,
            },
        )
        run_master_data_sheets_export(self.export_hook, self.stores)


@beartype
@dataclass(frozen=True, slots=True)
class UpdateMachineSettingsInput:
    machine_id: MachineId
    include_in_no_sales_monitoring: bool
    create_visit_on_no_sales: bool
    include_in_visit_photo_review: bool
    actor_telegram_user_id: int
    coffee_machine_model_id: str | None = None
    stand_type_id: str | None = None
    stand_color_id: str | None = None
    apply_equipment_catalogs: bool = False


@beartype
@dataclass(slots=True)
class UpdateMachineSettings:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    catalogs: CoffeeEquipmentCatalogs | None = None

    @beartype
    def execute(self, input: UpdateMachineSettingsInput) -> None:
        existing = self.stores.machines.get(input.machine_id)
        if existing is None:
            raise MasterDataCommandRejected(
                f"unknown machine_id {input.machine_id.value!r}",
                code="machine_not_found",
            )
        machine = existing
        if input.apply_equipment_catalogs:
            if self.catalogs is None:
                raise MasterDataCommandRejected(
                    "equipment catalogs are not configured",
                    code="unknown_catalog_entry",
                )
            machine = apply_equipment_to_machine(
                existing,
                self.catalogs,
                model_id=input.coffee_machine_model_id,
                stand_type_id=input.stand_type_id,
                stand_color_id=input.stand_color_id,
            )
        now = self.now_factory()
        saved = replace(
            machine,
            include_in_no_sales_monitoring=input.include_in_no_sales_monitoring,
            create_visit_on_no_sales=input.create_visit_on_no_sales,
            include_in_visit_photo_review=input.include_in_visit_photo_review,
        )
        self.stores.machines.upsert(saved)
        payload = {
            "machine_id": input.machine_id.value,
            "include_in_no_sales_monitoring": str(input.include_in_no_sales_monitoring),
            "create_visit_on_no_sales": str(input.create_visit_on_no_sales),
            "include_in_visit_photo_review": str(input.include_in_visit_photo_review),
        }
        if input.apply_equipment_catalogs:
            payload["coffee_machine_model_id"] = saved.coffee_machine_model_id or ""
            payload["stand_type_id"] = saved.stand_type_id or ""
            payload["stand_color_id"] = saved.stand_color_id or ""
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="update_machine_settings",
            payload=payload,
        )


@beartype
@dataclass(frozen=True, slots=True)
class MoveMachineToStorageInput:
    machine_id: MachineId
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class MoveMachineToStorage:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    export_hook: MasterDataExportHook | None = None

    @beartype
    def execute(self, input: MoveMachineToStorageInput) -> None:
        open_placement = self.stores.placements.get_open(input.machine_id)
        if open_placement is None:
            raise MasterDataCommandRejected(
                f"no open placement for machine {input.machine_id.value!r}",
                code="NoOpenPlacement",
            )
        machine = self.stores.machines.get(input.machine_id)
        if machine is None:
            raise MasterDataCommandRejected(
                f"unknown machine_id {input.machine_id.value!r}",
                code="UnknownMachine",
            )
        now = self.now_factory()
        self.stores.placements.update(
            MasterPlacement(
                placement_id=open_placement.placement_id,
                machine_id=open_placement.machine_id,
                location_id=open_placement.location_id,
                valid_from=open_placement.valid_from,
                valid_to=now,
            )
        )
        self.stores.machines.upsert(replace(machine, status=MachineStatus.IN_STORAGE))
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="MoveMachineToStorage",
            payload={"machine_id": input.machine_id.value},
        )
        run_master_data_sheets_export(self.export_hook, self.stores)


@beartype
@dataclass(frozen=True, slots=True)
class PlaceMachineFromStorageInput:
    machine_id: MachineId
    name: str
    city: str
    street: str
    house: str
    latitude: Decimal | None
    longitude: Decimal | None
    create_new_location: bool
    location_id: str | None
    actor_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class PlaceMachineFromStorageResult:
    location_id: str
    machine_id: MachineId
    placement_id: str


@beartype
@dataclass(slots=True)
class PlaceMachineFromStorage:
    stores: MasterDataStores
    now_factory: Callable[[], datetime]
    export_hook: MasterDataExportHook | None = None

    @beartype
    def execute(self, input: PlaceMachineFromStorageInput) -> PlaceMachineFromStorageResult:
        machine = self.stores.machines.get(input.machine_id)
        if machine is None:
            raise MasterDataCommandRejected(
                f"unknown machine_id {input.machine_id.value!r}",
                code="UnknownMachine",
            )
        if machine.status is not MachineStatus.IN_STORAGE:
            raise MasterDataCommandRejected(
                f"machine {input.machine_id.value!r} is not in_storage",
                code="WrongMachineStatus",
            )
        if self.stores.placements.get_open(input.machine_id) is not None:
            raise MasterDataCommandRejected(
                f"open placement already exists for machine {input.machine_id.value!r}",
                code="OpenPlacementExists",
            )
        _validate_coordinates(input.latitude, input.longitude)
        now = self.now_factory()
        if input.create_new_location:
            location_id = allocate_location_id(self.stores.counters)
            location = _build_location(
                location_id=location_id,
                name=input.name,
                city=input.city,
                street=input.street,
                house=input.house,
                latitude=input.latitude,
                longitude=input.longitude,
            )
            self.stores.locations.upsert(location)
        else:
            if input.location_id is None:
                raise MasterDataCommandRejected(
                    "location_id required when create_new_location is False",
                    code="MissingLocationId",
                )
            existing = self.stores.locations.get(input.location_id)
            if existing is None:
                raise MasterDataCommandRejected(
                    f"unknown location_id {input.location_id!r}",
                    code="UnknownLocation",
                )
            location_id = input.location_id
            location = existing
        placement_id = str(uuid4())
        self.stores.placements.insert(
            MasterPlacement(
                placement_id=placement_id,
                machine_id=input.machine_id,
                location_id=location_id,
                valid_from=now,
                valid_to=None,
            )
        )
        self.stores.machines.upsert(replace(machine, status=MachineStatus.ACTIVE_ON_SITE))
        _append_audit(
            self.stores,
            at=now,
            actor_telegram_user_id=input.actor_telegram_user_id,
            command="PlaceMachineFromStorage",
            payload={
                "location_id": location_id,
                "machine_id": input.machine_id.value,
                "placement_id": placement_id,
                "name": location.name,
                "city": location.city,
                "street": location.street,
                "house": location.house,
                "display_name": location.display_name,
            },
        )
        run_master_data_sheets_export(self.export_hook, self.stores)
        return PlaceMachineFromStorageResult(
            location_id=location_id,
            machine_id=input.machine_id,
            placement_id=placement_id,
        )
