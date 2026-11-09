from __future__ import annotations

from beartype import beartype

MIN_PROD_SECRET_LENGTH = 16
FORBIDDEN_PROD_SECRETS = frozenset(
    {
        "dev-webhook-secret",
        "dev-revision-form-token-secret",
        "dev-loading-form-token-secret",
    },
)


@beartype
def validate_prod_secret_strength(*, setting_name: str, value: str) -> None:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{setting_name} must be set when ENVIRONMENT=prod")
    if len(stripped) < MIN_PROD_SECRET_LENGTH:
        raise ValueError(
            f"{setting_name} must be at least {MIN_PROD_SECRET_LENGTH} characters "
            "when ENVIRONMENT=prod",
        )
    if stripped in FORBIDDEN_PROD_SECRETS:
        raise ValueError(
            f"{setting_name} must not use the dev placeholder when ENVIRONMENT=prod",
        )
