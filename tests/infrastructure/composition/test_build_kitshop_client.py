from __future__ import annotations

import json
import ssl
from pathlib import Path

import httpx
import pytest

from src.config.kitshop import KitShopSettings
from src.infrastructure.composition.factories.integrations import (
    build_kitshop_client,
    kitshop_ssl_context_allowing_expired_peer,
)
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.not_configured_client import (
    NotConfiguredKitShopClient,
)
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
)

# OpenSSL X509_V_FLAG_NO_CHECK_TIME — same numeric bit as in integrations factory.
_X509_V_FLAG_NO_CHECK_TIME = 0x200000


def _write_single_shop_accounts(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": "a",
                    "company_id": 1,
                    "kit_company_id": 10,
                    "platform": "kit_shop",
                    "role": "default",
                    "login": "u1",
                    "password": "p1",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_build_kitshop_client_not_configured_without_file(
    tmp_path: Path,
) -> None:
    settings = KitShopSettings(accounts_path=tmp_path / "missing.json")
    client = build_kitshop_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, NotConfiguredKitShopClient)


def test_build_kitshop_client_requires_single_kit_shop_account(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.json"
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": "a",
                    "company_id": 1,
                    "kit_company_id": 10,
                    "platform": "kit_shop",
                    "role": "default",
                    "login": "u1",
                    "password": "p1",
                },
                {
                    "account_key": "b",
                    "company_id": 2,
                    "kit_company_id": 11,
                    "platform": "kit_shop",
                    "role": "default",
                    "login": "u2",
                    "password": "p2",
                },
            ]
        ),
        encoding="utf-8",
    )
    settings = KitShopSettings(accounts_path=path)
    with pytest.raises(ValueError, match="ровно один"):
        build_kitshop_client(
            settings,
            request_id_store=InMemoryKitVendingRequestIdStore(),
            require_single_shop_account=True,
        )


def test_build_kitshop_client_single_account_returns_http_client(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.json"
    _write_single_shop_accounts(path)
    settings = KitShopSettings(accounts_path=path)
    client = build_kitshop_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitShopHttpClient)
    client.close()


def test_build_kitshop_client_passes_max_consecutive_high_requests(
    tmp_path: Path,
) -> None:
    # self-check: build_kitshop_client max_consecutive_high_requests
    path = tmp_path / "accounts.json"
    _write_single_shop_accounts(path)
    settings = KitShopSettings(
        accounts_path=path,
        max_consecutive_high_requests=2,
    )
    client = build_kitshop_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitShopHttpClient)
    assert client.api._rate_limiter.max_consecutive_high_requests == 2
    client.close()


def test_kitshop_ssl_context_keeps_hostname_and_ca_checks() -> None:
    ctx = kitshop_ssl_context_allowing_expired_peer()
    assert ctx.verify_flags & _X509_V_FLAG_NO_CHECK_TIME
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_build_kitshop_client_default_verify_without_expired_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "accounts.json"
    _write_single_shop_accounts(path)
    captured: list[dict[str, object]] = []
    real_client = httpx.Client

    def tracking_client(*args: object, **kwargs: object) -> httpx.Client:
        captured.append(dict(kwargs))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", tracking_client)
    settings = KitShopSettings(
        accounts_path=path,
        tls_allow_expired_peer_certificate=False,
    )
    client = build_kitshop_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitShopHttpClient)
    assert len(captured) == 1
    assert "verify" not in captured[0]
    assert captured[0].get("timeout") == 60.0
    client.close()


def test_build_kitshop_client_uses_no_check_time_context_when_flag_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "accounts.json"
    _write_single_shop_accounts(path)
    captured: list[dict[str, object]] = []
    real_client = httpx.Client

    def tracking_client(*args: object, **kwargs: object) -> httpx.Client:
        captured.append(dict(kwargs))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", tracking_client)
    settings = KitShopSettings(
        accounts_path=path,
        tls_allow_expired_peer_certificate=True,
    )
    client = build_kitshop_client(
        settings,
        request_id_store=InMemoryKitVendingRequestIdStore(),
    )
    assert isinstance(client, KitShopHttpClient)
    assert len(captured) == 1
    verify = captured[0]["verify"]
    assert isinstance(verify, ssl.SSLContext)
    assert verify is not False
    assert verify.verify_flags & _X509_V_FLAG_NO_CHECK_TIME
    assert verify.check_hostname is True
    assert verify.verify_mode == ssl.CERT_REQUIRED
    client.close()
