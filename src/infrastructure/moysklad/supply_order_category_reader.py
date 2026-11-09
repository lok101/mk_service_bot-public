from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from beartype import beartype

from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)
from src.config.moysklad import MoySkladSettings
from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_API_BASE_URL
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.integrations.moysklad.expand import (
    EXPAND_MAX_LIMIT,
    SUPPLY_ORDER_CATEGORY_PRODUCT_EXPAND,
)
from src.infrastructure.integrations.moysklad.http import (
    get_sync_backoff,
    get_sync_in_flight,
    get_sync_rate_limiter,
    is_parallel_limit_error,
)
from src.infrastructure.rate_limiting import (
    MoySkladApiPriority,
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncInFlightLimiter,
    SyncRateLimiter,
)

_LOGGER = logging.getLogger(__name__)


@beartype
class MoySkladSupplyOrderCategoryReader:
    """Targeted live product facts for supply-order category classification."""

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        attr_shelf_life_days_id: str,
        request_attempts: int = 3,
        rate_limiter: SyncRateLimiter | PrioritySyncRateLimiter | None = None,
        backoff: SyncGlobalBackoff | None = None,
        in_flight: SyncInFlightLimiter | None = None,
    ) -> None:
        self._client = http_client
        self._attr_shelf_life_days_id = attr_shelf_life_days_id.strip().lower()
        self._request_attempts = max(1, request_attempts)
        self._folder_parent_cache: dict[str, str | None] = {}
        self._folder_parent_index: dict[str, str | None] = {}
        self._rate_limiter = rate_limiter
        self._backoff = backoff
        self._in_flight = in_flight

    @beartype
    def set_folder_parent_index(self, index: Mapping[str, str | None]) -> None:
        """Optional id→parent map for chains deeper than expand depth 3."""
        self._folder_parent_index = {
            key.strip(): (value.strip() if isinstance(value, str) and value.strip() else None)
            for key, value in index.items()
            if key.strip()
        }
        self._folder_parent_cache.clear()

    @beartype
    def refresh_folder_parent_index(self) -> None:
        """Page all productfolders and replace the id→parent index."""
        index: dict[str, str | None] = {}
        offset = 0
        while True:
            payload = self._get(
                "/entity/productfolder",
                params={"limit": EXPAND_MAX_LIMIT, "offset": offset},
            )
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            page_count = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                folder_id = row.get("id")
                if not isinstance(folder_id, str) or not folder_id.strip():
                    folder_id = _meta_uuid(row.get("meta"))
                if not isinstance(folder_id, str) or not folder_id.strip():
                    continue
                folder_id = folder_id.strip()
                index[folder_id] = _folder_parent_id(row)
                page_count += 1
            if page_count < EXPAND_MAX_LIMIT:
                break
            offset += EXPAND_MAX_LIMIT
        self.set_folder_parent_index(index)

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MoySkladSettings,
        *,
        attr_shelf_life_days_id: str,
    ) -> MoySkladSupplyOrderCategoryReader:
        token = settings.api_token
        if token is None:
            msg = "MoySklad API token is required"
            raise ValueError(msg)
        client = httpx.Client(
            base_url=MOYSKLAD_API_BASE_URL,
            headers={
                "Authorization": f"Bearer {token.get_secret_value()}",
                "Accept-Encoding": "gzip",
            },
            timeout=settings.request_timeout_seconds,
        )
        return cls(
            http_client=client,
            attr_shelf_life_days_id=attr_shelf_life_days_id,
            request_attempts=settings.request_attempts,
        )

    @beartype
    def close(self) -> None:
        self._client.close()

    @beartype
    def fetch_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Sequence[SupplyOrderCategoryProductFacts] | SupplyOrderCategoryFactsFetchFailed:
        unique = tuple(dict.fromkeys(code.strip() for code in catalog_codes if code.strip()))
        if not unique:
            return ()
        try:
            cards = self._fetch_product_cards(unique)
            facts: list[SupplyOrderCategoryProductFacts] = []
            for code, payload in cards.items():
                ancestors = self._folder_ancestors_from_product(payload)
                days = _shelf_life_days(payload, attr_id=self._attr_shelf_life_days_id)
                facts.append(
                    SupplyOrderCategoryProductFacts(
                        catalog_code=code,
                        folder_ancestor_ids=ancestors,
                        shelf_life_days=days,
                    ),
                )
            return tuple(facts)
        except MoySkladConnectionError, MoySkladAPIError, MoySkladRequestError, httpx.HTTPError:
            _LOGGER.info("supply_order_category_ms_fetch_failed", exc_info=True)
            return SupplyOrderCategoryFactsFetchFailed()

    @beartype
    def _fetch_product_cards(self, product_codes: Sequence[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        requested = set(product_codes)
        for offset in range(0, len(product_codes), EXPAND_MAX_LIMIT):
            chunk = product_codes[offset : offset + EXPAND_MAX_LIMIT]
            filter_value = ";".join(f"code={code}" for code in chunk)
            payload = self._get(
                "/entity/product",
                params={
                    "filter": filter_value,
                    "limit": len(chunk),
                    "expand": SUPPLY_ORDER_CATEGORY_PRODUCT_EXPAND,
                },
            )
            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = row.get("code")
                if isinstance(code, str) and code in requested and code not in out:
                    out[code] = row
        return out

    @beartype
    def _folder_ancestors(self, folder_id: str) -> tuple[str, ...]:
        chain: list[str] = []
        seen: set[str] = set()
        current: str | None = folder_id.strip()
        while current and current not in seen:
            seen.add(current)
            chain.append(current)
            parent = self._resolve_folder_parent(current)
            current = parent
        return tuple(chain)

    @beartype
    def _folder_ancestors_from_product(self, payload: Mapping[str, Any]) -> tuple[str, ...]:
        folder = payload.get("productFolder")
        if not isinstance(folder, dict):
            return ()
        if _is_meta_only_link(folder):
            raise MoySkladAPIError("productFolder expand ignored (meta-only)")
        expanded, may_have_more = _ancestors_from_expanded_folder(folder)
        if not expanded:
            folder_id = _product_folder_id(payload)
            return self._folder_ancestors(folder_id) if folder_id else ()
        if not may_have_more:
            return expanded
        # Continue past expand depth via index / GET when last node still has parent.
        tail_id = expanded[-1]
        parent = self._resolve_folder_parent(tail_id)
        if parent is None or parent in expanded:
            return expanded
        rest = self._folder_ancestors(parent)
        return expanded + rest

    @beartype
    def _resolve_folder_parent(self, folder_id: str) -> str | None:
        if folder_id in self._folder_parent_cache:
            return self._folder_parent_cache[folder_id]
        if self._folder_parent_index:
            if folder_id not in self._folder_parent_index:
                raise MoySkladAPIError(f"folder parent unknown after index refresh: {folder_id}")
            parent = self._folder_parent_index[folder_id]
            self._folder_parent_cache[folder_id] = parent
            return parent
        payload = self._get(f"/entity/productfolder/{folder_id}", params={})
        parent = _folder_parent_id(payload if isinstance(payload, dict) else {})
        self._folder_parent_cache[folder_id] = parent
        return parent

    def _resolved_rate_limiter(self) -> SyncRateLimiter | PrioritySyncRateLimiter:
        return self._rate_limiter if self._rate_limiter is not None else get_sync_rate_limiter()

    def _resolved_backoff(self) -> SyncGlobalBackoff:
        return self._backoff if self._backoff is not None else get_sync_backoff()

    def _resolved_in_flight(self) -> SyncInFlightLimiter:
        return self._in_flight if self._in_flight is not None else get_sync_in_flight()

    @beartype
    def _gated_http_get(self, path: str, *, params: Mapping[str, Any]) -> httpx.Response:
        self._resolved_backoff().wait_if_blocked()
        self._resolved_rate_limiter().acquire(priority=MoySkladApiPriority.LOW)
        in_flight = self._resolved_in_flight()
        in_flight.acquire()
        try:
            return self._client.get(path, params=dict(params))
        finally:
            in_flight.release()

    @beartype
    def _get(self, path: str, *, params: Mapping[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self._request_attempts + 1):
            try:
                response = self._gated_http_get(path, params=params)
            except httpx.HTTPError as error:
                last_error = error
                continue
            if response.status_code >= 500:
                last_error = MoySkladAPIError(f"MoySklad HTTP {response.status_code}")
                continue
            if response.status_code >= 400:
                payload: dict[str, Any]
                try:
                    body = response.json()
                    payload = body if isinstance(body, dict) else {}
                except ValueError:
                    payload = {}
                request_error = MoySkladRequestError(response.status_code, payload)
                if request_error.status == 429 and attempt < self._request_attempts:
                    parallel = is_parallel_limit_error(request_error)
                    _LOGGER.warning(
                        "supply_order_category_ms_rate_limit path=%s codes=%s parallel=%s",
                        path,
                        request_error.codes,
                        parallel,
                    )
                    if not parallel:
                        self._resolved_backoff().trigger_backoff()
                    last_error = request_error
                    continue
                raise request_error
            body = response.json()
            if not isinstance(body, dict):
                raise MoySkladAPIError("MoySklad response is not an object")
            return body
        if isinstance(last_error, MoySkladAPIError):
            raise last_error
        if isinstance(last_error, MoySkladRequestError):
            raise last_error
        raise MoySkladConnectionError(str(last_error) if last_error else "MoySklad GET failed")


def _meta_uuid(meta: object) -> str | None:
    if not isinstance(meta, dict):
        return None
    href = meta.get("href")
    if not isinstance(href, str) or not href:
        return None
    return href.rstrip("/").rsplit("/", 1)[-1] or None


def _product_folder_id(payload: Mapping[str, Any]) -> str | None:
    folder = payload.get("productFolder")
    if isinstance(folder, dict):
        folder_id = folder.get("id")
        if isinstance(folder_id, str) and folder_id.strip():
            return folder_id.strip()
        return _meta_uuid(folder.get("meta"))
    return None


def _is_meta_only_link(entity: Mapping[str, Any]) -> bool:
    """True when link has meta href but no expanded body ``id`` (expand ignored)."""
    body_id = entity.get("id")
    has_body_id = isinstance(body_id, str) and bool(body_id.strip())
    return (not has_body_id) and _meta_uuid(entity.get("meta")) is not None


def _ancestors_from_expanded_folder(
    folder: Mapping[str, Any],
) -> tuple[tuple[str, ...], bool]:
    """Return (ancestor ids, may_have_more beyond expand depth)."""
    chain: list[str] = []
    seen: set[str] = set()
    current: object = folder
    may_have_more = False
    while isinstance(current, dict):
        folder_id = current.get("id")
        if not isinstance(folder_id, str) or not folder_id.strip():
            folder_id = _meta_uuid(current.get("meta"))
        if not isinstance(folder_id, str) or not folder_id.strip():
            break
        folder_id = folder_id.strip()
        if folder_id in seen:
            break
        seen.add(folder_id)
        chain.append(folder_id)
        nested = current.get("productFolder")
        if nested is None:
            may_have_more = False
            break
        if not isinstance(nested, dict):
            may_have_more = False
            break
        nested_id = nested.get("id")
        if isinstance(nested_id, str) and nested_id.strip():
            current = nested
            continue
        meta_id = _meta_uuid(nested.get("meta"))
        if meta_id is not None:
            # Meta-only parent link: expand depth exhausted or ignored.
            may_have_more = True
            break
        may_have_more = False
        break
    return tuple(chain), may_have_more


def _folder_parent_id(payload: Mapping[str, Any]) -> str | None:
    parent = payload.get("productFolder")
    if isinstance(parent, dict):
        parent_id = parent.get("id")
        if isinstance(parent_id, str) and parent_id.strip():
            return parent_id.strip()
        return _meta_uuid(parent.get("meta"))
    return None


def _shelf_life_days(payload: Mapping[str, Any], *, attr_id: str) -> int | None:
    attributes = payload.get("attributes")
    if not isinstance(attributes, list):
        return None
    target = attr_id.strip().lower()
    for item in attributes:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or raw_id.strip().lower() != target:
            continue
        return _as_nonneg_int(item.get("value"))
    return None


def _as_nonneg_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        as_int = int(value)
        return as_int if as_int >= 0 else None
    if isinstance(value, str) and value.strip():
        try:
            as_int = int(value.strip())
        except ValueError:
            return None
        return as_int if as_int >= 0 else None
    return None
