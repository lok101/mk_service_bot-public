from __future__ import annotations

from pydantic import Field

from src.config._base import ServiceSettingsBase


class EffectsWorkerSettings(ServiceSettingsBase):
    status_collection: str = Field(
        default="effects_worker_status",
        validation_alias="MONGODB_EFFECTS_WORKER_STATUS_COLLECTION",
        min_length=1,
    )
