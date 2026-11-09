from __future__ import annotations

import os
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


def _running_under_pytest() -> bool:
    return (
        os.getenv("MK_SERVICE_BOT_DISABLE_DOTENV") == "1"
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
        or "PYTEST_VERSION" in os.environ
        or "pytest" in sys.modules
        or any("pytest" in arg for arg in sys.argv)
    )


def default_env_file() -> str | None:
    """Dotenv path, or None under pytest (isolated from dev ``.env.dev``)."""
    return None if _running_under_pytest() else ".env.dev"


DEFAULT_ENV_FILE = default_env_file()


class ServiceSettingsBase(BaseSettings):
    """Base for per-integration settings; each service gets its own module."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )
