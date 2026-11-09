"""Domain ID value objects.

Runtime EventId generation (aggregate → new event):
- MachineOperations, TechnicianSettlement: EventId(f"event-{uuid.uuid4()}")
- TechnicianAccountability: EventId(str(uuid.uuid4())) — legacy, do not change without migration

EventId.value is an opaque string for event store / outbox; infrastructure does not parse prefixes.
"""

from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("TechnicianId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class MachineId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("MachineId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class RevisionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("RevisionId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class EventId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("EventId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class BatchId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("BatchId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class FindingId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("FindingId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class AccountabilityId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("AccountabilityId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationSessionId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("ReconciliationSessionId value must not be empty")


@beartype
@dataclass(frozen=True, slots=True)
class ResidualDocumentId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("ResidualDocumentId value must not be empty")
