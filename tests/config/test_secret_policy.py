from __future__ import annotations

import pytest

from src.config.secret_policy import (
    FORBIDDEN_PROD_SECRETS,
    MIN_PROD_SECRET_LENGTH,
    validate_prod_secret_strength,
)


def test_validate_prod_secret_strength_accepts_long_value() -> None:
    validate_prod_secret_strength(
        setting_name="BOT_TOKEN",
        value="a" * MIN_PROD_SECRET_LENGTH,
    )


def test_validate_prod_secret_strength_rejects_placeholder() -> None:
    placeholder = next(iter(FORBIDDEN_PROD_SECRETS))
    with pytest.raises(ValueError, match="must not use the dev placeholder"):
        validate_prod_secret_strength(setting_name="BOT_TOKEN", value=placeholder)


def test_validate_prod_secret_strength_rejects_short_value() -> None:
    with pytest.raises(ValueError, match="must be at least"):
        validate_prod_secret_strength(setting_name="BOT_TOKEN", value="short")


def test_validate_prod_secret_strength_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="must be set"):
        validate_prod_secret_strength(setting_name="BOT_TOKEN", value="")
