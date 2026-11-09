from __future__ import annotations

from typing import Literal

from beartype import beartype
from pydantic import Field, SecretStr, model_validator

from src.config._base import ServiceSettingsBase

PhotoStorageBackend = Literal["memory", "s3"]
S3AddressingStyle = Literal["auto", "path", "virtual"]


class ObjectStorageSettings(ServiceSettingsBase):
    backend: PhotoStorageBackend = Field(
        default="memory",
        validation_alias="PHOTO_STORAGE_BACKEND",
    )
    s3_endpoint_url: str | None = Field(default=None, validation_alias="S3_ENDPOINT_URL")
    s3_bucket: str = Field(default="", validation_alias="S3_BUCKET")
    s3_access_key_id: str = Field(default="", validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr | None = Field(
        default=None,
        validation_alias="S3_SECRET_ACCESS_KEY",
    )
    s3_region: str | None = Field(default=None, validation_alias="S3_REGION")
    s3_key_prefix: str = Field(default="mk-service-bot", validation_alias="S3_KEY_PREFIX")
    s3_addressing_style: S3AddressingStyle = Field(
        default="auto",
        validation_alias="S3_ADDRESSING_STYLE",
    )
    photo_storage_ttl_days: int | None = Field(
        default=None,
        validation_alias="PHOTO_STORAGE_TTL_DAYS",
        gt=0,
    )

    @model_validator(mode="after")
    def validate_s3_settings(self) -> ObjectStorageSettings:
        if self.backend != "s3":
            return self
        if not self.s3_bucket.strip():
            raise ValueError("S3_BUCKET is required when PHOTO_STORAGE_BACKEND=s3")
        if not self.s3_access_key_id.strip():
            raise ValueError("S3_ACCESS_KEY_ID is required when PHOTO_STORAGE_BACKEND=s3")
        if self.s3_secret_access_key is None:
            raise ValueError("S3_SECRET_ACCESS_KEY is required when PHOTO_STORAGE_BACKEND=s3")
        return self

    @beartype
    def normalized_key_prefix(self) -> str:
        return self.s3_key_prefix.strip().strip("/")
