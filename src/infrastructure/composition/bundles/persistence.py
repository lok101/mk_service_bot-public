from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import redis as redis_lib
from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class PersistenceBundle:
    mongo_client: Any | None
    redis_client: redis_lib.Redis | None
