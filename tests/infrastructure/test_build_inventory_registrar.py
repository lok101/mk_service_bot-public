from __future__ import annotations

from src.config.moysklad import MoySkladSettings
from src.infrastructure.composition.factories import build_moysklad_client


def test_build_moysklad_client_returns_none_when_unconfigured() -> None:
    assert build_moysklad_client(MoySkladSettings.model_construct(api_token=None)) is None
