from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from beartype import beartype

from src.config.moysklad import MoySkladSettings
from src.infrastructure.integrations.moysklad.constants import MOYSKLAD_API_BASE_URL
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladAPIError,
    MoySkladConnectionError,
    MoySkladRequestError,
)
from src.infrastructure.integrations.moysklad.http import (
    get_sync_backoff,
    get_sync_in_flight,
    get_sync_rate_limiter,
    is_parallel_limit_error,
)
from src.infrastructure.moysklad.purchase_prices.models import (
    LastSupplyProcurementRow,
    PurchaseAttributes,
    PurchaseAttributesBatchResult,
)
from src.infrastructure.rate_limiting import (
    MoySkladApiPriority,
    PrioritySyncRateLimiter,
    SyncGlobalBackoff,
    SyncInFlightLimiter,
    SyncRateLimiter,
)

logger = logging.getLogger(__name__)

# Network blip pause between attempts. Must not equal request timeout (30s default):
# that made procurement mirror sync stall for minutes on transient errors.
_DEFAULT_NETWORK_RETRY_DELAY_SECONDS = 1.0


def _is_moysklad_errors_body(payload: dict[str, Any]) -> bool:
    errors = payload.get("errors")
    return isinstance(errors, list)


@beartype
def _kopecks_to_rubles_str(value: object) -> str:
    amount = Decimal(str(value)) / Decimal(100)
    return format(amount, "f")


@beartype
def _attr_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str) and value.strip():
        return Decimal(value.replace(",", "."))
    return None


@beartype
def _attr_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


@beartype
def _as_volume(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        as_decimal = Decimal(value.replace(",", "."))
        if as_decimal == as_decimal.to_integral_value():
            return int(as_decimal)
    return 0


@beartype
@dataclass(frozen=True, slots=True)
class _ProductCard:
    code: str
    product_uuid: str
    volume: int
    # None = attributes key missing on list row (miss → detail GET).
    attributes: tuple[Mapping[str, Any], ...] | None = None


@beartype
class MoySkladPurchasePricesHttpClient:
    """Last-supply purchase attributes for matrix deploy.

    One ``/entity/supply`` GET per product card (concurrency-capped). This is a
    known volume/429 risk on large SKU unions — prefer lowering concurrency /
    batching over adding more per-entity GETs. See ``moysklad.expand`` audit
    and matrix purchase-price design.
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client,
        main_store_id: str,
        supply_fetch_concurrency: int = 2,
        request_attempts: int = 3,
        retry_delay_seconds: float = 0.0,
        rate_limit_backoff_seconds: float = 60.0,
        package_quantity_attr_id: str = "",
        supplier_product_name_attr_id: str = "",
        rate_limiter: SyncRateLimiter | PrioritySyncRateLimiter | None = None,
        backoff: SyncGlobalBackoff | None = None,
        in_flight: SyncInFlightLimiter | None = None,
    ) -> None:
        self._client = http_client
        self._main_store_id = main_store_id
        self._supply_fetch_concurrency = max(1, supply_fetch_concurrency)
        self._request_attempts = max(1, request_attempts)
        self._retry_delay_seconds = retry_delay_seconds
        self._rate_limit_backoff_seconds = max(0.0, rate_limit_backoff_seconds)
        self._package_quantity_attr_id = package_quantity_attr_id.strip()
        self._supplier_product_name_attr_id = supplier_product_name_attr_id.strip()
        self._rate_limiter = rate_limiter
        self._backoff = backoff
        self._in_flight = in_flight

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MoySkladSettings,
        *,
        supply_fetch_concurrency: int,
        package_quantity_attr_id: str = "",
        supplier_product_name_attr_id: str = "",
    ) -> MoySkladPurchasePricesHttpClient:
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
        capped = min(max(1, supply_fetch_concurrency), settings.http_max_in_flight)
        return cls(
            http_client=client,
            main_store_id=settings.main_store_id.strip(),
            supply_fetch_concurrency=capped,
            request_attempts=settings.request_attempts,
            retry_delay_seconds=_DEFAULT_NETWORK_RETRY_DELAY_SECONDS,
            rate_limit_backoff_seconds=float(settings.rate_limit_backoff_seconds),
            package_quantity_attr_id=package_quantity_attr_id,
            supplier_product_name_attr_id=supplier_product_name_attr_id,
        )

    @beartype
    def fetch_purchase_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesBatchResult:
        if not product_codes:
            return PurchaseAttributesBatchResult(attributes={}, cards_found=0)

        cards = self._fetch_product_cards(product_codes)
        cards_found = len(cards)
        if cards_found == 0:
            self._log_fetch_counters(
                requested_count=len(product_codes),
                cards_found=0,
                supply_ok=0,
                supply_empty_price_zero=0,
                supply_http_failed=0,
            )
            return PurchaseAttributesBatchResult(attributes={}, cards_found=0)

        attributes: dict[str, PurchaseAttributes] = {}
        failed: set[str] = set()
        supply_ok = 0
        supply_empty_price_zero = 0

        with ThreadPoolExecutor(max_workers=self._supply_fetch_concurrency) as pool:
            futures = {pool.submit(self._fetch_supply_for_card, card): card for card in cards}
            for future in as_completed(futures):
                card = futures[future]
                try:
                    attrs, empty_zero = future.result()
                except Exception:  # noqa: BLE001
                    failed.add(card.code)
                    continue
                if attrs is None:
                    failed.add(card.code)
                    continue
                attributes[card.code] = attrs
                if empty_zero:
                    supply_empty_price_zero += 1
                else:
                    supply_ok += 1

        self._log_fetch_counters(
            requested_count=len(product_codes),
            cards_found=cards_found,
            supply_ok=supply_ok,
            supply_empty_price_zero=supply_empty_price_zero,
            supply_http_failed=len(failed),
        )
        return PurchaseAttributesBatchResult(
            attributes=attributes,
            cards_found=cards_found,
            supply_http_failed=frozenset(failed),
        )

    @beartype
    def fetch_last_supply_procurement(self, catalog_code: str) -> LastSupplyProcurementRow | None:
        cards = self._fetch_product_cards(frozenset({catalog_code}))
        if not cards:
            return LastSupplyProcurementRow(
                catalog_code=catalog_code,
                supplier_id=None,
                supplier_name=None,
                last_buy_price=None,
                supply_moment=None,
            )
        card = cards[0]
        try:
            payload = self._fetch_supply_payload(card.product_uuid)
            package_quantity, supplier_product_name = self._resolve_product_custom_attrs(card)
        except MoySkladConnectionError, MoySkladAPIError, MoySkladRequestError:
            return None
        row = self._parse_last_supply_procurement(
            payload,
            catalog_code=catalog_code,
            product_uuid=card.product_uuid,
        )
        return LastSupplyProcurementRow(
            catalog_code=row.catalog_code,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            last_buy_price=row.last_buy_price,
            supply_moment=row.supply_moment,
            package_quantity=package_quantity,
            supplier_product_name=supplier_product_name,
        )

    @beartype
    def close(self) -> None:
        self._client.close()

    @beartype
    def _fetch_product_cards(self, product_codes: frozenset[str]) -> list[_ProductCard]:
        unique_codes = list(product_codes)
        filter_value = ";".join(f"code={code}" for code in unique_codes)
        payload = self._get(
            "/entity/product",
            params={"filter": filter_value, "limit": len(unique_codes)},
        )
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        requested = set(unique_codes)
        cards: list[_ProductCard] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            product_uuid = row.get("id")
            if (
                not isinstance(code, str)
                or code not in requested
                or code in seen
                or not isinstance(product_uuid, str)
                or not product_uuid
            ):
                continue
            seen.add(code)
            raw_attrs = row.get("attributes")
            attributes: tuple[Mapping[str, Any], ...] | None
            if isinstance(raw_attrs, list):
                attributes = tuple(item for item in raw_attrs if isinstance(item, Mapping))
            else:
                attributes = None
            cards.append(
                _ProductCard(
                    code=code,
                    product_uuid=product_uuid,
                    volume=_as_volume(row.get("volume")),
                    attributes=attributes,
                ),
            )
        return cards

    @beartype
    def _fetch_supply_for_card(
        self,
        card: _ProductCard,
    ) -> tuple[PurchaseAttributes | None, bool]:
        try:
            buy_price = self._last_supply_price(card.product_uuid)
        except MoySkladConnectionError, MoySkladAPIError, MoySkladRequestError:
            return None, False
        empty_zero = buy_price == "0"
        return (
            PurchaseAttributes(buy_price=buy_price, volume=card.volume),
            empty_zero,
        )

    @beartype
    def _fetch_supply_payload(self, product_uuid: str) -> Any:
        product_href = f"{MOYSKLAD_API_BASE_URL}/entity/product/{product_uuid}"
        store_href = f"{MOYSKLAD_API_BASE_URL}/entity/store/{self._main_store_id}"
        return self._get(
            "/entity/supply",
            params={
                "expand": "positions.assortment,agent",
                "limit": 1,
                "order": "moment,desc",
                "filter": f"assortment={product_href};store={store_href}",
            },
        )

    @beartype
    def _resolve_product_custom_attrs(
        self,
        card: _ProductCard,
    ) -> tuple[Decimal | None, str | None]:
        if not self._package_quantity_attr_id and not self._supplier_product_name_attr_id:
            return None, None
        if card.attributes is not None:
            return self._parse_product_custom_attrs(card.attributes)
        return self._fetch_product_custom_attrs(card.product_uuid)

    @beartype
    def _fetch_product_custom_attrs(
        self,
        product_uuid: str,
    ) -> tuple[Decimal | None, str | None]:
        payload = self._get(f"/entity/product/{product_uuid}", params={})
        if not isinstance(payload, dict):
            return None, None
        attributes = payload.get("attributes")
        if not isinstance(attributes, list):
            return None, None
        parsed = tuple(item for item in attributes if isinstance(item, Mapping))
        return self._parse_product_custom_attrs(parsed)

    @beartype
    def _parse_product_custom_attrs(
        self,
        attributes: tuple[Mapping[str, Any], ...] | list[Any],
    ) -> tuple[Decimal | None, str | None]:
        package_quantity: Decimal | None = None
        supplier_product_name: str | None = None
        for item in attributes:
            if not isinstance(item, Mapping):
                continue
            attr_id = item.get("id")
            if not isinstance(attr_id, str):
                continue
            if attr_id == self._package_quantity_attr_id:
                package_quantity = _attr_decimal(item.get("value"))
            elif attr_id == self._supplier_product_name_attr_id:
                supplier_product_name = _attr_str(item.get("value"))
        return package_quantity, supplier_product_name

    @beartype
    def _last_supply_price(self, product_uuid: str) -> str:
        payload = self._fetch_supply_payload(product_uuid)
        return self._max_matching_position_price(payload, product_uuid=product_uuid)

    @beartype
    def _parse_last_supply_procurement(
        self,
        payload: Any,
        *,
        catalog_code: str,
        product_uuid: str,
    ) -> LastSupplyProcurementRow:
        empty = LastSupplyProcurementRow(
            catalog_code=catalog_code,
            supplier_id=None,
            supplier_name=None,
            last_buy_price=None,
            supply_moment=None,
        )
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return empty
        supply = rows[0]
        if not isinstance(supply, dict):
            return empty
        prices = self._matching_position_prices(supply, product_uuid=product_uuid)
        if not prices:
            return empty
        supplier_id, supplier_name = self._parse_supply_agent(supply.get("agent"))
        return LastSupplyProcurementRow(
            catalog_code=catalog_code,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            last_buy_price=max(prices) / Decimal(100),
            supply_moment=self._parse_supply_moment(supply.get("moment")),
        )

    @beartype
    def _max_matching_position_price(
        self,
        payload: Any,
        *,
        product_uuid: str,
    ) -> str:
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return "0"
        supply = rows[0]
        if not isinstance(supply, dict):
            return "0"
        prices = self._matching_position_prices(supply, product_uuid=product_uuid)
        if not prices:
            return "0"
        return _kopecks_to_rubles_str(max(prices))

    @beartype
    def _matching_position_prices(
        self,
        supply: Mapping[str, Any],
        *,
        product_uuid: str,
    ) -> list[Decimal]:
        positions = supply.get("positions")
        position_rows: list[Any] = []
        if isinstance(positions, dict):
            raw_rows = positions.get("rows")
            if isinstance(raw_rows, list):
                position_rows = raw_rows
        elif isinstance(positions, list):
            position_rows = positions

        prices: list[Decimal] = []
        for position in position_rows:
            if not isinstance(position, dict):
                continue
            assortment = position.get("assortment")
            if not isinstance(assortment, dict):
                continue
            if assortment.get("id") != product_uuid:
                continue
            price_raw = position.get("price")
            if price_raw is None:
                continue
            prices.append(Decimal(str(price_raw)))
        return prices

    @beartype
    def _parse_supply_agent(self, agent: object) -> tuple[str | None, str | None]:
        if not isinstance(agent, dict):
            return None, None
        agent_id = agent.get("id")
        if not isinstance(agent_id, str) or not agent_id:
            meta = agent.get("meta")
            href = meta.get("href") if isinstance(meta, dict) else None
            agent_id = href.rsplit("/", maxsplit=1)[-1] if isinstance(href, str) and href else None
        if not isinstance(agent_id, str) or not agent_id:
            agent_id = None
        name = agent.get("name")
        supplier_name = name if isinstance(name, str) and name else None
        return agent_id, supplier_name

    @beartype
    def _parse_supply_moment(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        text = str(value)
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=UTC)
        except ValueError:
            return None

    @beartype
    def _log_fetch_counters(
        self,
        *,
        requested_count: int,
        cards_found: int,
        supply_ok: int,
        supply_empty_price_zero: int,
        supply_http_failed: int,
    ) -> None:
        logger.info(
            "moysklad_purchase_attributes_fetched",
            extra={
                "store_id": self._main_store_id,
                "requested_count": requested_count,
                "cards_found": cards_found,
                "supply_ok": supply_ok,
                "supply_empty_price_zero": supply_empty_price_zero,
                "supply_http_failed": supply_http_failed,
                "concurrency": self._supply_fetch_concurrency,
            },
        )

    def _resolved_rate_limiter(self) -> SyncRateLimiter | PrioritySyncRateLimiter:
        return self._rate_limiter if self._rate_limiter is not None else get_sync_rate_limiter()

    def _resolved_backoff(self) -> SyncGlobalBackoff:
        return self._backoff if self._backoff is not None else get_sync_backoff()

    def _resolved_in_flight(self) -> SyncInFlightLimiter:
        return self._in_flight if self._in_flight is not None else get_sync_in_flight()

    @beartype
    def _gated_get(self, path: str, *, params: Mapping[str, str | int]) -> Any:
        self._resolved_backoff().wait_if_blocked()
        self._resolved_rate_limiter().acquire(priority=MoySkladApiPriority.LOW)
        in_flight = self._resolved_in_flight()
        in_flight.acquire()
        try:
            response = self._client.get(path, params=params)
            return self._parse_response(response)
        finally:
            in_flight.release()

    @beartype
    def _get(self, path: str, *, params: Mapping[str, str | int]) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._request_attempts + 1):
            try:
                return self._gated_get(path, params=params)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as error:
                last_error = error
                if attempt == self._request_attempts:
                    raise MoySkladConnectionError(str(error)) from error
                if self._retry_delay_seconds > 0:
                    time.sleep(self._retry_delay_seconds)
            except MoySkladRequestError as error:
                if error.status != 429 or attempt == self._request_attempts:
                    raise
                last_error = error
                parallel = is_parallel_limit_error(error)
                logger.warning(
                    "moysklad_purchase_prices_rate_limit_backoff path=%s attempt=%s "
                    "codes=%s parallel=%s",
                    path,
                    attempt,
                    error.codes,
                    parallel,
                )
                if not parallel:
                    self._resolved_backoff().trigger_backoff()
        raise MoySkladConnectionError(str(last_error or "unreachable"))

    @beartype
    def _parse_response(self, response: httpx.Response) -> Any:
        raw = response.content
        payload: dict[str, Any] | None = None
        if raw.strip():
            try:
                parsed = response.json()
            except ValueError as error:
                raise MoySkladAPIError(
                    f"MoySklad HTTP {response.status_code}: invalid JSON body",
                ) from error
            payload = parsed if isinstance(parsed, dict) else {"error": parsed}

        if response.status_code >= 400:
            if payload is not None and _is_moysklad_errors_body(payload):
                raise MoySkladRequestError(response.status_code, payload)
            raise MoySkladAPIError(
                f"MoySklad HTTP {response.status_code}: {payload or response.text}",
            )

        if payload is None:
            return {}
        return payload
