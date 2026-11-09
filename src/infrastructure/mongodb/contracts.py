from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

type MongoScalar = str | int | float | bool | datetime | None
type MongoPayload = dict[str, MongoScalar | list[MongoScalar]]


MACHINE_OPERATIONS_AGGREGATE_TYPE = "MachineOperations"


@beartype
@dataclass(frozen=True, slots=True)
class MongoEventDocument:
    event_id: str
    event_type: str
    aggregate_id: str
    aggregate_type: str
    aggregate_version: int
    occurred_at: datetime
    payload: MongoPayload
    metadata: MongoPayload
