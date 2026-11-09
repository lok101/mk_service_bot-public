from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import validate_matrix_worker_settings
from src.config.telegram import TelegramSettings

from .fakes import _worker_settings


def test_supply_fetch_concurrency_default_is_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MATRIX_SUPPLY_FETCH_CONCURRENCY", raising=False)
    settings = MatrixAutomationSettings()
    assert settings.supply_fetch_concurrency == 2


@pytest.mark.parametrize("value", ["0", "33", "-1"])
def test_supply_fetch_concurrency_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("MATRIX_SUPPLY_FETCH_CONCURRENCY", value)
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()


def test_supply_fetch_concurrency_accepts_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATRIX_SUPPLY_FETCH_CONCURRENCY", "1")
    assert MatrixAutomationSettings().supply_fetch_concurrency == 1
    monkeypatch.setenv("MATRIX_SUPPLY_FETCH_CONCURRENCY", "32")
    assert MatrixAutomationSettings().supply_fetch_concurrency == 32


def test_curved_margin_env_defaults() -> None:
    """happy: defaults из спека §Env."""
    settings = MatrixAutomationSettings()
    assert settings.scale_price_min == Decimal("10")
    assert settings.scale_price_max == Decimal("500")
    assert settings.scale_rate_min == Decimal("0.1")
    assert settings.scale_rate_max == Decimal("2.0")
    assert settings.curvature_min == Decimal("0.5")
    assert settings.curvature_max == Decimal("3")
    assert settings.margin_floor_min == Decimal("10")
    assert settings.margin_floor_max == Decimal("100")


@pytest.mark.parametrize(
    ("env_min", "env_max"),
    [
        ("MATRIX_SCALE_PRICE_MIN", "MATRIX_SCALE_PRICE_MAX"),
        ("MATRIX_SCALE_RATE_MIN", "MATRIX_SCALE_RATE_MAX"),
        ("MATRIX_CURVATURE_MIN", "MATRIX_CURVATURE_MAX"),
        ("MATRIX_MARGIN_FLOOR_MIN", "MATRIX_MARGIN_FLOOR_MAX"),
    ],
)
def test_curved_margin_env_min_gt_max_rejected(
    monkeypatch: pytest.MonkeyPatch,
    env_min: str,
    env_max: str,
) -> None:
    """error: min > max → ValidationError при старте."""
    monkeypatch.setenv(env_min, "10")
    monkeypatch.setenv(env_max, "1")
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()


def test_legacy_margin_env_fields_absent() -> None:
    """edge: старые abs/% поля удалены из модели."""
    fields = set(MatrixAutomationSettings.model_fields)
    curved = {
        "scale_price_min",
        "scale_price_max",
        "scale_rate_min",
        "scale_rate_max",
        "curvature_min",
        "curvature_max",
        "margin_floor_min",
        "margin_floor_max",
    }
    assert curved <= fields
    margin_fields = {name for name in fields if name.startswith("margin_")}
    assert margin_fields == {"margin_floor_min", "margin_floor_max"}


def test_moysklad_main_store_id_reads_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MOYSKLAD_MAIN_STORE_ID",
        "11111111-1111-1111-1111-111111111111",
    )
    settings = MoySkladSettings()
    assert settings.main_store_id == "11111111-1111-1111-1111-111111111111"


def test_moysklad_main_store_id_default_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOYSKLAD_MAIN_STORE_ID", raising=False)
    assert MoySkladSettings().main_store_id == ""


def test_enabled_worker_requires_moysklad_main_store_id(tmp_path: Path) -> None:
    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text(
        '[{"login": "u", "password": "p", "company_id": 42}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="MOYSKLAD_MAIN_STORE_ID"):
        validate_matrix_worker_settings(
            _worker_settings(
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("ms-token"),
                    main_store_id="",
                ),
                kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
                telegram=TelegramSettings.model_construct(
                    bot_token=SecretStr("test-bot-token"),
                    alert_chat_id=12345,
                ),
            ),
        )


def test_enabled_worker_rejects_non_uuid_main_store_id(tmp_path: Path) -> None:
    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text(
        '[{"login": "u", "password": "p", "company_id": 42}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="MOYSKLAD_MAIN_STORE_ID"):
        validate_matrix_worker_settings(
            _worker_settings(
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("ms-token"),
                    main_store_id="not-a-uuid",
                ),
                kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
                telegram=TelegramSettings.model_construct(
                    bot_token=SecretStr("test-bot-token"),
                    alert_chat_id=12345,
                ),
            ),
        )
