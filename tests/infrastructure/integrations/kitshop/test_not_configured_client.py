from __future__ import annotations

import pytest

from src.infrastructure.integrations.kitshop.not_configured_client import (
    NotConfiguredKitShopClient,
)


def test_not_configured_client_raises_without_http() -> None:
    client = NotConfiguredKitShopClient()
    with pytest.raises(RuntimeError, match="not configured"):
        client.get_shops()
