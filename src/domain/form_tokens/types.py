from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import MachineId, TechnicianId

InventoryFormPurpose = Literal["loading"]


@beartype
@dataclass(frozen=True, slots=True)
class RevisionFormTokenPayload:
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str


@beartype
@dataclass(frozen=True, slots=True)
class InventoryFormTokenPayload:
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str


LoadingFormTokenPayload = InventoryFormTokenPayload


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseInventoryTokenPayload:
    technician_id: TechnicianId
    issued_at: datetime
    nonce: str


SnackInventoryFormPurpose = Literal["snack_inventory_now", "snack_inventory_as_of"]


@beartype
@dataclass(frozen=True, slots=True)
class SnackInventoryFormTokenPayload:
    purpose: SnackInventoryFormPurpose
    technician_id: TechnicianId
    machine_code: str
    fingerprint_id: str
    cell_keys: tuple[tuple[str, str, int], ...]
    product_codes: tuple[str, ...]
    issued_at: datetime
    nonce: str


MicromarketInventoryFormPurpose = Literal[
    "micromarket_inventory_now",
    "micromarket_inventory_as_of",
]


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketInventoryFormTokenPayload:
    purpose: MicromarketInventoryFormPurpose
    technician_id: TechnicianId
    machine_code: str
    fingerprint_id: str
    product_codes: tuple[str, ...]
    issued_at: datetime
    nonce: str


CoffeeFormPurpose = Literal["revision", "loading"]


@beartype
@dataclass(frozen=True, slots=True)
class CoffeeFormTokenPayload:
    purpose: CoffeeFormPurpose
    technician_id: TechnicianId
    machine_id: MachineId
    product_codes: tuple[str, ...]
    issued_at: datetime
    nonce: str


@beartype
@dataclass(frozen=True, slots=True)
class PeekedFormToken:
    purpose: str | None
    technician_id: TechnicianId
    machine_id: MachineId | None


@beartype
@dataclass(frozen=True, slots=True)
class VerifiedInventoryFormToken:
    purpose: InventoryFormPurpose
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str


@beartype
@dataclass(frozen=True, slots=True)
class PeekedMachineFormToken:
    technician_id: TechnicianId
    machine_id: MachineId
    issued_at: datetime
    nonce: str
    purpose: str | None
