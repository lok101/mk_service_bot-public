from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import certifi
import httpx
from beartype import beartype
from pymongo import MongoClient

from src.application.inventory_reconciliation.ports import KitVendingClient
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.application.master_data.companies import KitPlatform, KitPlatformRole
from src.application.master_data.company_directory import KitCompanyDirectory
from src.application.master_data.ports import CompanyStore
from src.application.matrix_automation import MatrixDeployer
from src.application.product_identity import DomainProductResolve
from src.config.kitshop import KitShopSettings
from src.config.kitvending import KitVendingSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.http_client import KitShopApiClient
from src.infrastructure.integrations.kitshop.not_configured_client import (
    NotConfiguredKitShopClient,
)
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    InMemoryKitShopReferenceSnapshotStore,
    KitShopReferenceSnapshotStore,
)
from src.infrastructure.integrations.kitvending.catalog_cache import (
    CatalogCache,
    CatalogFetchResult,
)
from src.infrastructure.integrations.kitvending.catalog_merge import fetch_merged_catalog
from src.infrastructure.integrations.kitvending.client import KitVendingHttpClient
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.not_configured_client import (
    NotConfiguredKitVendingClient,
)
from src.infrastructure.integrations.kitvending.platform_accounts import (
    KitPlatformAccount,
    accounts_file_is_valid,
    load_kit_platform_accounts,
)
from src.infrastructure.integrations.kitvending.platform_accounts_validation import (
    validate_platform_accounts,
)
from src.infrastructure.integrations.kitvending.request_id_store import (
    InMemoryKitVendingRequestIdStore,
    KitVendingRequestIdStore,
)
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.kitvending.deploy.client import KitVendingDeployClient
from src.infrastructure.kitvending.deploy.coordinator import BatchMatrixDeployCoordinator
from src.infrastructure.mongodb.kitshop_reference_snapshots import (
    MongoKitShopReferenceSnapshotStore,
)
from src.infrastructure.mongodb.kitvending_request_ids import (
    MongoDatabaseSource,
    MongoKitVendingRequestIdStore,
)
from src.infrastructure.rate_limiting import (
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncRateLimiter,
)


@beartype
def _kitvending_request_id_store_required(settings: Settings) -> bool:
    if not accounts_file_is_valid(settings.kitvending.accounts_path):
        return False
    return settings.kitvending.ingestion_enabled or settings.matrix_automation.worker_enabled


@beartype
def build_kitvending_request_id_store(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> KitVendingRequestIdStore:
    if _kitvending_request_id_store_required(settings) and not settings.mongodb.is_configured:
        raise ValueError(
            "KitVending RequestId store requires Mongo when sales ingest "
            "or matrix-worker is enabled"
        )
    if _kitvending_request_id_store_required(settings) and settings.mongodb.is_configured:
        return MongoKitVendingRequestIdStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    return InMemoryKitVendingRequestIdStore()


@beartype
def _select_sales_poll_account(accounts: tuple[KitPlatformAccount, ...]) -> KitPlatformAccount:
    sales_poll = [
        account
        for account in accounts
        if account.platform is KitPlatform.KIT_VENDING
        and account.role is KitPlatformRole.SALES_POLL
    ]
    if len(sales_poll) > 1:
        raise ValueError("multiple sales_poll vending accounts")
    if not sales_poll:
        raise ValueError("sales_poll vending account required")
    return sales_poll[0]


@beartype
def _is_catalog_account(account: KitPlatformAccount, company_store: CompanyStore) -> bool:
    if account.platform is not KitPlatform.KIT_VENDING:
        return False
    if account.role is KitPlatformRole.CATALOG:
        return True
    company = company_store.get(account.company_id)
    if company is None:
        return False
    for binding in company.platform_bindings:
        if (
            binding.platform is account.platform
            and binding.kit_company_id == account.kit_company_id
            and KitPlatformRole.CATALOG in binding.roles
        ):
            return True
    return False


@beartype
def _catalog_accounts(
    accounts: tuple[KitPlatformAccount, ...],
    *,
    company_store: CompanyStore,
) -> tuple[KitPlatformAccount, ...]:
    return tuple(account for account in accounts if _is_catalog_account(account, company_store))


@beartype
def _build_api_client(
    account: KitPlatformAccount,
    *,
    settings: KitVendingSettings,
    http: httpx.Client,
    request_id_store: KitVendingRequestIdStore,
) -> KitVendingApiClient:
    return KitVendingApiClient(
        account=account,
        settings=settings,
        http_client=http,
        request_id_store=request_id_store,
        rate_limiter=SyncRateLimiter(
            max_requests=settings.requests_per_window,
            time_window=settings.window_seconds,
        ),
        backoff=SyncGlobalBackoff(timeout=settings.backoff_seconds),
    )


@beartype
def _kit_platform_accounts_require_validation(settings: KitVendingSettings) -> bool:
    return settings.ingestion_enabled


@beartype
def build_kitvending_client(
    settings: KitVendingSettings,
    *,
    request_id_store: KitVendingRequestIdStore,
    company_store: CompanyStore | None = None,
    http_client: httpx.Client | None = None,
    skip_store: MachineSaleSkipStore | None = None,
    require_binding_validation: bool | None = None,
    domain_product_identity_enabled: bool = False,
    resolve_sale_code: Callable[[str], DomainProductResolve] | None = None,
) -> KitVendingClient:
    if not accounts_file_is_valid(settings.accounts_path):
        return NotConfiguredKitVendingClient()

    loaded = load_kit_platform_accounts(settings.accounts_path)
    accounts = tuple(loaded)
    should_validate = (
        require_binding_validation
        if require_binding_validation is not None
        else _kit_platform_accounts_require_validation(settings)
    )
    if should_validate:
        if company_store is None:
            raise ValueError("company_store required when platform account validation is enabled")
        validate_platform_accounts(accounts, company_store=company_store)

    sales_poll = _select_sales_poll_account(accounts)
    http = http_client or httpx.Client(timeout=60.0)
    main_api = _build_api_client(
        sales_poll,
        settings=settings,
        http=http,
        request_id_store=request_id_store,
    )
    catalog_source = (
        _catalog_accounts(accounts, company_store=company_store)
        if company_store is not None
        else tuple(
            account
            for account in accounts
            if account.platform is KitPlatform.KIT_VENDING
            and account.role is KitPlatformRole.CATALOG
        )
    )
    catalog_clients = tuple(
        _build_api_client(
            account,
            settings=settings,
            http=http,
            request_id_store=request_id_store,
        )
        for account in catalog_source
    )
    catalog_cache = CatalogCache(
        ttl_seconds=settings.catalog_cache_ttl_seconds,
        now=time.monotonic,
    )

    def catalog_fetch() -> CatalogFetchResult:
        return fetch_merged_catalog(catalog_clients)

    company_directory = KitCompanyDirectory(company_store) if company_store is not None else None

    return KitVendingHttpClient(
        main_api=main_api,
        catalog_clients=catalog_clients,
        catalog_fetch=catalog_fetch,
        catalog_cache=catalog_cache,
        shared_http_client=http,
        skip_store=skip_store,
        company_directory=company_directory,
        domain_product_identity_enabled=domain_product_identity_enabled,
        resolve_sale_code=resolve_sale_code,
    )


# OpenSSL X509_V_FLAG_NO_CHECK_TIME (openssl/x509_vfy.h). Python 3.14 has no
# ssl.VERIFY_* name for this bit; keep the numeric flag from OpenSSL.
_X509_V_FLAG_NO_CHECK_TIME = 0x200000


@beartype
def kitshop_ssl_context_allowing_expired_peer() -> ssl.SSLContext:
    """httpx-default CA bundle (certifi); skip only peer certificate notAfter/notBefore."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.verify_flags |= _X509_V_FLAG_NO_CHECK_TIME
    return ctx


@beartype
def build_kitshop_reference_snapshot_store(
    settings: Settings,
    *,
    client: Any = None,
) -> KitShopReferenceSnapshotStore:
    if settings.mongodb.is_configured and client is not None:
        return MongoKitShopReferenceSnapshotStore.from_settings(
            settings.mongodb,
            client=client,
        )
    return InMemoryKitShopReferenceSnapshotStore()


@beartype
def kit_shop_company_id(settings: KitShopSettings) -> int | None:
    """Company id from the accounts file. Does not open an HTTP client."""
    if not accounts_file_is_valid(settings.accounts_path):
        return None
    shop_accounts = [
        account
        for account in load_kit_platform_accounts(settings.accounts_path)
        if account.platform is KitPlatform.KIT_SHOP
    ]
    if len(shop_accounts) != 1:
        return None
    return int(shop_accounts[0].kit_company_id)


@beartype
def build_kitshop_client(
    settings: KitShopSettings,
    *,
    request_id_store: KitVendingRequestIdStore,
    http_client: httpx.Client | None = None,
    require_single_shop_account: bool = True,
) -> KitShopHttpClient | NotConfiguredKitShopClient:
    """Build Kit Shop facade; 0 kit_shop accounts → NotConfigured; >1 → ValueError."""
    if not accounts_file_is_valid(settings.accounts_path):
        return NotConfiguredKitShopClient()

    accounts = load_kit_platform_accounts(settings.accounts_path)
    shop_accounts = [a for a in accounts if a.platform is KitPlatform.KIT_SHOP]
    if not shop_accounts:
        return NotConfiguredKitShopClient()
    if require_single_shop_account and len(shop_accounts) != 1:
        raise ValueError(
            f"ожидается ровно один account platform=kit_shop "
            f"(найдено {len(shop_accounts)}) в {settings.accounts_path}"
        )

    account = shop_accounts[0]
    owns_http = http_client is None
    if http_client is not None:
        http = http_client
    elif settings.tls_allow_expired_peer_certificate:
        http = httpx.Client(
            timeout=60.0,
            verify=kitshop_ssl_context_allowing_expired_peer(),
        )
    else:
        http = httpx.Client(timeout=60.0)
    api = KitShopApiClient(
        account=account,
        settings=settings,
        http_client=http,
        request_id_store=request_id_store,
        rate_limiter=PrioritySyncRateLimiter(
            max_requests=settings.requests_per_window,
            time_window=settings.window_seconds,
            max_consecutive_high_requests=settings.max_consecutive_high_requests,
        ),
        backoff=SyncGlobalBackoff(timeout=settings.backoff_seconds),
        owns_http_client=owns_http,
    )
    return KitShopHttpClient(api=api, settings=settings)


@beartype
def build_matrix_deployer(
    settings: Settings,
    *,
    request_id_store: KitVendingRequestIdStore,
    company_store: CompanyStore | None = None,
    http_client: httpx.Client | None = None,
    require_binding_validation: bool | None = None,
) -> MatrixDeployer:
    kit = settings.kitvending
    matrix = settings.matrix_automation
    clients: list[KitVendingDeployClient] = []
    if accounts_file_is_valid(kit.accounts_path):
        loaded = load_kit_platform_accounts(kit.accounts_path)
        accounts = tuple(loaded)
        should_validate = (
            require_binding_validation
            if require_binding_validation is not None
            else matrix.worker_enabled
        )
        if should_validate:
            if company_store is None:
                raise ValueError(
                    "company_store required when platform account validation is enabled",
                )
            validate_platform_accounts(accounts, company_store=company_store)
        http = http_client or httpx.Client(timeout=60.0)
        vending_accounts = [
            account for account in accounts if account.platform is KitPlatform.KIT_VENDING
        ]
        for account in vending_accounts:
            clients.append(
                KitVendingDeployClient(
                    account=account,
                    settings=kit,
                    http_client=http,
                    request_id_store=request_id_store,
                    rate_limiter=SyncRateLimiter(
                        max_requests=kit.requests_per_window,
                        time_window=kit.window_seconds,
                    ),
                    backoff=SyncGlobalBackoff(timeout=kit.backoff_seconds),
                )
            )
    return BatchMatrixDeployCoordinator(
        clients=tuple(clients),
        blocking_label=matrix.blocking_cell_label,
        display_timezone=settings.service_calendar.zone_info(),
        now=lambda: datetime.now(tz=UTC),
        load_timeout_seconds=matrix.load_timeout_seconds,
        apply_timeout_seconds=matrix.apply_timeout_seconds,
        status_poll_interval_seconds=matrix.status_poll_interval_seconds,
        command_send_delay_seconds=matrix.command_send_delay_seconds,
        poll_api_max_retries=matrix.poll_api_max_retries,
        retry_send_command_delay_seconds=matrix.retry_send_command_delay_seconds,
    )


@beartype
def build_moysklad_client(settings: MoySkladSettings) -> MoySkladClient | None:
    if not settings.is_configured:
        return None
    return MoySkladClient(settings=settings)
