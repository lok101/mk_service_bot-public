from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from beartype import beartype


class ReferenceDataSourceId(StrEnum):
    COFFEE_TECHNICIAN_LOCATIONS = "coffee_technician_locations"
    SNACK_TECHNICIAN_LOCATIONS = "snack_technician_locations"
    BOT_USERS = "bot_users"
    TECHNICIANS_DIRECTORY = "technicians_directory"
    LOCATIONS_DIRECTORY = "locations_directory"
    PRODUCT_VITRINE = "product_vitrine"  # Sheets витрина
    PRODUCT_CATALOG = "product_catalog"  # MS display catalog
    PRODUCT_MULTIPLIERS = "product_multipliers"


APP_REFERENCE_DATA_SOURCE_IDS: frozenset[ReferenceDataSourceId] = frozenset(
    {
        ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS,
        ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS,
        ReferenceDataSourceId.BOT_USERS,
        ReferenceDataSourceId.TECHNICIANS_DIRECTORY,
        ReferenceDataSourceId.PRODUCT_VITRINE,
    },
)


def matrix_catalog_tab_source_id(title: str) -> str:
    return f"matrix_catalog:{title.strip()}"


@dataclass(frozen=True, slots=True)
class ReferenceDataSyncError:
    message: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ReferenceDataSnapshot:
    source_id: ReferenceDataSourceId
    rows: tuple[tuple[str, ...], ...]
    content_hash: str
    last_fetched_at: datetime
    content_updated_at: datetime
    last_sync_error: ReferenceDataSyncError | None = None


@beartype
def compute_content_hash(rows: Sequence[Sequence[str]]) -> str:
    normalized = [list(row) for row in rows]
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
