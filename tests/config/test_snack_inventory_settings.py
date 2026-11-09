from __future__ import annotations

import pytest
from pydantic import SecretStr

from src.config.snack_loading import SnackLoadingSettings


def test_snack_inventory_settings_not_required_on_default_settings() -> None:
    settings = SnackLoadingSettings()
    assert settings.inventory_form_now_template_id is None
    assert settings.inventory_form_as_of_template_id is None
    assert settings.inventory_form_now_token_secret is None
    assert settings.inventory_form_as_of_token_secret is None
    assert settings.inventory_form_token_entry_id is None
    assert settings.sale_unresolved_alert_min == 10


def test_require_snack_inventory_forms_raises_when_missing() -> None:
    settings = SnackLoadingSettings()
    with pytest.raises(ValueError, match="SNACK_INVENTORY"):
        settings.require_snack_inventory_forms()


def test_require_snack_inventory_forms_ok_when_complete() -> None:
    settings = SnackLoadingSettings.model_construct(
        inventory_form_now_template_id="tpl-now",
        inventory_form_as_of_template_id="tpl-as-of",
        inventory_form_now_token_secret=SecretStr("now-secret"),
        inventory_form_as_of_token_secret=SecretStr("as-of-secret"),
        inventory_form_token_entry_id="entry.snack",
    )
    settings.require_snack_inventory_forms()


def test_has_any_snack_inventory_forms_env_false_when_empty() -> None:
    assert SnackLoadingSettings().has_any_snack_inventory_forms_env is False


def test_has_any_snack_inventory_forms_env_true_when_partial() -> None:
    settings = SnackLoadingSettings.model_construct(
        inventory_form_now_token_secret=SecretStr("only-now"),
    )
    assert settings.has_any_snack_inventory_forms_env is True
