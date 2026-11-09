from __future__ import annotations

from beartype import beartype

from src.config.secret_policy import validate_prod_secret_strength
from src.config.settings import Settings


@beartype
def _admin_mount_enabled(settings: Settings) -> bool:
    return (
        settings.location_roster.enabled
        or settings.master_data.enabled
        or settings.master_data.users_enabled
        or settings.master_data.technicians_enabled
        or settings.master_data.companies_enabled
        or settings.settlement_analysis.enabled
        or settings.visit_photo_review.enabled
    )


@beartype
def _validate_prod_secret(*, setting_name: str, value: str, errors: list[str]) -> None:
    try:
        validate_prod_secret_strength(setting_name=setting_name, value=value)
    except ValueError as exc:
        errors.append(str(exc))


@beartype
def validate_runtime_settings(settings: Settings) -> None:
    """Fail fast in production when required integrations would silently use stubs or memory."""
    if settings.is_test:
        return

    if settings.is_dev:
        if settings.moysklad.is_configured:
            raise ValueError("MOYSKLAD_API_TOKEN must not be set when ENVIRONMENT=dev")
        return

    if not settings.is_production:
        return

    errors: list[str] = []

    if not settings.mongodb.is_configured:
        errors.append("MONGODB_URI must be set when ENVIRONMENT=prod")

    if not settings.redis.is_configured:
        errors.append("REDIS_URI must be set when ENVIRONMENT=prod")

    moysklad = settings.moysklad
    if not moysklad.is_configured:
        errors.append("MOYSKLAD_API_TOKEN must be set when ENVIRONMENT=prod")
    elif not moysklad.organization_id.strip():
        errors.append("MOYSKLAD_ORGANIZATION_ID must be set when ENVIRONMENT=prod")
    elif not moysklad.project_id.strip():
        errors.append("MOYSKLAD_PROJECT_ID must be set when ENVIRONMENT=prod")

    google_sheets = settings.google_sheets
    if not google_sheets.credentials_file.strip():
        errors.append(
            "GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE must be set when ENVIRONMENT=prod",
        )
    if not google_sheets.is_product_catalog_configured:
        errors.append(
            "PRODUCT_CATALOG_SPREADSHEET_ID and PRODUCT_CATALOG_SHEET_ID "
            "must be set when ENVIRONMENT=prod",
        )
    if not google_sheets.is_coffee_technician_locations_configured:
        errors.append(
            "COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID, "
            "COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID, "
            "and USERS_SHEET_ID must be set when ENVIRONMENT=prod",
        )
    if not google_sheets.is_technicians_directory_configured:
        errors.append(
            "TECHNICIANS_DIRECTORY_SPREADSHEET_ID and "
            "TECHNICIANS_DIRECTORY_SHEET_ID "
            "must be set when ENVIRONMENT=prod",
        )

    telegram = settings.telegram
    _validate_prod_secret(
        setting_name="BOT_TOKEN",
        value=telegram.bot_token.get_secret_value(),
        errors=errors,
    )
    if not telegram.uses_webhook:
        errors.append("TELEGRAM_WEBHOOK_IP must be set when ENVIRONMENT=prod")
    else:
        _validate_prod_secret(
            setting_name="TELEGRAM_WEBHOOK_SECRET",
            value=telegram.webhook_secret_value() or "",
            errors=errors,
        )

    if telegram.alert_chat_id is None:
        errors.append("TELEGRAM_ALERT_CHAT_ID must be set when ENVIRONMENT=prod")

    google_forms = settings.google_forms
    _validate_prod_secret(
        setting_name="GOOGLE_FORMS_WEBHOOK_SECRET",
        value=google_forms.webhook_secret.get_secret_value(),
        errors=errors,
    )
    _validate_prod_secret(
        setting_name="REVISION_FORM_TOKEN_SECRET",
        value=google_forms.revision_form_token_secret.get_secret_value(),
        errors=errors,
    )
    _validate_prod_secret(
        setting_name="LOADING_FORM_TOKEN_SECRET",
        value=google_forms.loading_form_token_secret.get_secret_value(),
        errors=errors,
    )
    _validate_prod_secret(
        setting_name="TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        value=google_forms.technician_warehouse_inventory_form_token_secret.get_secret_value(),
        errors=errors,
    )

    snack_loading = settings.snack_loading
    if snack_loading.inventory_form_now_token_secret is not None:
        _validate_prod_secret(
            setting_name="SNACK_INVENTORY_FORM_NOW_TOKEN_SECRET",
            value=snack_loading.inventory_form_now_token_secret.get_secret_value(),
            errors=errors,
        )
    if snack_loading.inventory_form_as_of_token_secret is not None:
        _validate_prod_secret(
            setting_name="SNACK_INVENTORY_FORM_AS_OF_TOKEN_SECRET",
            value=snack_loading.inventory_form_as_of_token_secret.get_secret_value(),
            errors=errors,
        )

    micromarket_loading = settings.micromarket_loading
    if micromarket_loading.inventory_form_now_token_secret is not None:
        _validate_prod_secret(
            setting_name="MICROMARKET_INVENTORY_FORM_NOW_TOKEN_SECRET",
            value=micromarket_loading.inventory_form_now_token_secret.get_secret_value(),
            errors=errors,
        )
    if micromarket_loading.inventory_form_as_of_token_secret is not None:
        _validate_prod_secret(
            setting_name="MICROMARKET_INVENTORY_FORM_AS_OF_TOKEN_SECRET",
            value=micromarket_loading.inventory_form_as_of_token_secret.get_secret_value(),
            errors=errors,
        )

    sales_monitoring = settings.sales_monitoring
    if sales_monitoring.worker_enabled:
        token = sales_monitoring.telegram_bot_token
        _validate_prod_secret(
            setting_name="SALES_MONITORING_TELEGRAM_BOT_TOKEN",
            value=token.get_secret_value() if token is not None else "",
            errors=errors,
        )

    event_reminders = settings.event_reminders
    if event_reminders.worker_enabled:
        token = event_reminders.telegram_bot_token
        _validate_prod_secret(
            setting_name="EVENT_REMINDERS_TELEGRAM_BOT_TOKEN",
            value=token.get_secret_value() if token is not None else "",
            errors=errors,
        )

    if _admin_mount_enabled(settings):
        session_secret = settings.master_data.session_secret
        _validate_prod_secret(
            setting_name="ADMIN_SESSION_SECRET",
            value=session_secret.get_secret_value() if session_secret is not None else "",
            errors=errors,
        )

    object_storage = settings.object_storage
    if object_storage.backend != "s3":
        errors.append(
            "PHOTO_STORAGE_BACKEND must be s3 when ENVIRONMENT=prod",
        )
    else:
        if object_storage.photo_storage_ttl_days is None:
            errors.append(
                "PHOTO_STORAGE_TTL_DAYS must be set when PHOTO_STORAGE_BACKEND=s3 "
                "and ENVIRONMENT=prod",
            )
        s3_secret = object_storage.s3_secret_access_key
        _validate_prod_secret(
            setting_name="S3_SECRET_ACCESS_KEY",
            value=s3_secret.get_secret_value() if s3_secret is not None else "",
            errors=errors,
        )

    if errors:
        raise ValueError("; ".join(errors))
