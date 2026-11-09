from __future__ import annotations

import json
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator

from src.config._base import ServiceSettingsBase
from src.domain.visit_photo_review import CatalogInvalid, parse_review_catalog


class VisitPhotoReviewSettings(ServiceSettingsBase):
    enabled: bool = Field(
        default=False,
        validation_alias="VISIT_PHOTO_REVIEW_ENABLED",
    )
    catalog_path: str = Field(
        default="",
        validation_alias="VISIT_PHOTO_REVIEW_CATALOG_PATH",
    )
    collection: str = Field(
        default="visit_photo_reviews",
        validation_alias="MONGODB_VISIT_PHOTO_REVIEW_COLLECTION",
        min_length=1,
    )
    profiles_collection: str = Field(
        default="visit_photo_profiles",
        validation_alias="MONGODB_VISIT_PHOTO_PROFILES_COLLECTION",
        min_length=1,
    )
    profile_strict: bool = Field(
        default=False,
        validation_alias="VISIT_PHOTO_PROFILE_STRICT",
    )
    session_secret: SecretStr | None = Field(
        default=None,
        validation_alias="ADMIN_SESSION_SECRET",
    )
    telegram_bot_username: str = Field(
        default="",
        validation_alias="TELEGRAM_BOT_USERNAME",
    )
    dev_stub_login_enabled: bool = Field(
        default=False,
        validation_alias="ADMIN_DEV_STUB_LOGIN_ENABLED",
    )

    @model_validator(mode="after")
    def validate_enabled_secrets(self) -> Self:
        if not self.enabled:
            return self
        if not self.catalog_path.strip():
            raise ValueError(
                "VISIT_PHOTO_REVIEW_CATALOG_PATH must be set when VISIT_PHOTO_REVIEW_ENABLED=true",
            )
        secret = ""
        if self.session_secret is not None:
            secret = self.session_secret.get_secret_value().strip()
        if not secret:
            raise ValueError(
                "ADMIN_SESSION_SECRET must be set when VISIT_PHOTO_REVIEW_ENABLED=true",
            )
        username = self.telegram_bot_username.strip()
        if username.startswith("@"):
            raise ValueError("TELEGRAM_BOT_USERNAME must not start with @")
        if not self.dev_stub_login_enabled and not username:
            raise ValueError(
                "TELEGRAM_BOT_USERNAME must be set when "
                "VISIT_PHOTO_REVIEW_ENABLED=true and ADMIN_DEV_STUB_LOGIN_ENABLED=false",
            )
        catalog_file = Path(self.catalog_path)
        if not catalog_file.is_file():
            raise ValueError(
                f"VISIT_PHOTO_REVIEW_CATALOG_PATH file not found: {self.catalog_path}",
            )
        try:
            payload = json.loads(catalog_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"VISIT_PHOTO_REVIEW_CATALOG_PATH is not valid JSON: {exc}",
            ) from exc
        try:
            parse_review_catalog(payload)
        except CatalogInvalid as exc:
            raise ValueError(str(exc)) from exc
        return self
