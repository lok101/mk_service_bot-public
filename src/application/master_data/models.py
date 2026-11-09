from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from beartype import beartype

from src.application.master_data.ports import CompanyStore, MasterDataCounterStore
from src.domain.ids import MachineId


class MachineKind(StrEnum):
    COFFEE = "coffee"
    SNACK = "snack"
    MICRO_MARKET = "micro_market"


class MachineStatus(StrEnum):
    ACTIVE_ON_SITE = "active_on_site"
    IN_STORAGE = "in_storage"


class LocationIdOverflow(Exception):
    """Location id decimal length exceeds 6 characters."""


class OpenPlacementExists(Exception):
    """Machine already has an open placement."""


@beartype
@dataclass(frozen=True, slots=True)
class MasterLocation:
    location_id: str
    name: str
    city: str
    street: str
    house: str
    display_name: str
    latitude: Decimal | None
    longitude: Decimal | None


@beartype
@dataclass(frozen=True, slots=True)
class MasterMachine:
    machine_id: MachineId
    kind: MachineKind
    status: MachineStatus
    label: str | None
    include_in_no_sales_monitoring: bool = True
    create_visit_on_no_sales: bool = True
    include_in_visit_photo_review: bool = True
    coffee_machine_model_id: str | None = None
    stand_type_id: str | None = None
    stand_color_id: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class MasterPlacement:
    placement_id: str
    machine_id: MachineId
    location_id: str
    valid_from: datetime
    valid_to: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class MasterDataAuditRecord:
    at: datetime
    actor_telegram_user_id: int
    command: str
    payload: dict[str, str]


MACHINE_COFFEE_COUNTER_KEY = "machine_coffee"
MACHINE_SNACK_COUNTER_KEY = "machine_snack"
MACHINE_MICRO_MARKET_COUNTER_KEY = "machine_micro_market"
LOCATION_COUNTER_KEY = "location"
SYSTEM_USER_COUNTER_KEY = "system_user"
TECHNICIAN_COUNTER_KEY = "technician"
COMPANY_COUNTER_KEY = "company"
_COFFEE_START = 101
_SNACK_START = 501
_MICRO_MARKET_START = 701
_LOCATION_START = 1
_SYSTEM_USER_START = 1
_TECHNICIAN_START = 1
_LOCATION_ID_MAX_LEN = 6


@beartype
def _allocate_with_floor(counter_store: MasterDataCounterStore, key: str, start: int) -> int:
    """Race-free floor: keep calling allocate_next until value >= start."""
    while True:
        value = counter_store.allocate_next(key)
        if value >= start:
            return value


@beartype
def allocate_machine_id(counter_store: MasterDataCounterStore, kind: MachineKind) -> MachineId:
    if kind is MachineKind.COFFEE:
        key, start = MACHINE_COFFEE_COUNTER_KEY, _COFFEE_START
    elif kind is MachineKind.SNACK:
        key, start = MACHINE_SNACK_COUNTER_KEY, _SNACK_START
    elif kind is MachineKind.MICRO_MARKET:
        key, start = MACHINE_MICRO_MARKET_COUNTER_KEY, _MICRO_MARKET_START
    else:
        raise ValueError(f"unsupported machine kind: {kind!r}")
    return MachineId(str(_allocate_with_floor(counter_store, key, start)))


@beartype
def allocate_location_id(counter_store: MasterDataCounterStore) -> str:
    next_id = _allocate_with_floor(counter_store, LOCATION_COUNTER_KEY, _LOCATION_START)
    as_str = str(next_id)
    if len(as_str) > _LOCATION_ID_MAX_LEN:
        raise LocationIdOverflow(
            f"location id {as_str!r} exceeds {_LOCATION_ID_MAX_LEN} characters",
        )
    return as_str


@beartype
def allocate_system_user_id(counter_store: MasterDataCounterStore) -> str:
    return str(_allocate_with_floor(counter_store, SYSTEM_USER_COUNTER_KEY, _SYSTEM_USER_START))


@beartype
def allocate_technician_id(counter_store: MasterDataCounterStore) -> str:
    return str(_allocate_with_floor(counter_store, TECHNICIAN_COUNTER_KEY, _TECHNICIAN_START))


@beartype
def allocate_company_id(
    counter_store: MasterDataCounterStore,
    *,
    store: CompanyStore,
) -> int:
    max_existing = max((c.company_id for c in store.list_all()), default=0)
    return _allocate_with_floor(counter_store, COMPANY_COUNTER_KEY, max_existing + 1)
