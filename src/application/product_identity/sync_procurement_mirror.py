from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

from src.application.product_identity.ports import (
    DomainProductStore,
    ProcurementAttributesFetcher,
    ProcurementMirrorStore,
)
from src.application.product_identity.procurement_mirror import (
    ProcurementFetchFailed,
    ProcurementMirror,
    ProcurementSupplySnapshot,
)

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class ProcurementMirrorSyncStats:
    requested: int
    upserted: int
    empty_supply: int
    http_failed: int
    pruned: int


@beartype
class SyncProcurementMirror:
    def __init__(
        self,
        *,
        enabled: bool,
        products: DomainProductStore,
        mirrors: ProcurementMirrorStore,
        fetcher: ProcurementAttributesFetcher,
        clock: Callable[[], datetime],
        supply_concurrency: int = 1,
    ) -> None:
        self._enabled = enabled
        self._products = products
        self._mirrors = mirrors
        self._fetcher = fetcher
        self._clock = clock
        self._supply_concurrency = max(1, supply_concurrency)

    @beartype
    def sync_all(self) -> ProcurementMirrorSyncStats:
        if not self._enabled:
            return _zero_stats()
        linked = self._linked_codes()
        stats = self._fetch_and_upsert(linked)
        pruned = 0
        for code in self._mirrors.codes():
            if code not in linked:
                self._mirrors.delete(code)
                pruned += 1
        result = ProcurementMirrorSyncStats(
            requested=stats.requested,
            upserted=stats.upserted,
            empty_supply=stats.empty_supply,
            http_failed=stats.http_failed,
            pruned=pruned,
        )
        self._log(result)
        return result

    @beartype
    def sync_codes(self, *catalog_codes: str | None) -> ProcurementMirrorSyncStats:
        if not self._enabled:
            return _zero_stats()
        codes = tuple(dict.fromkeys(code for code in catalog_codes if code))
        linked = self._linked_codes()
        to_fetch: list[str] = []
        pruned = 0
        for code in codes:
            if code not in linked:
                if self._mirrors.get(code) is not None:
                    self._mirrors.delete(code)
                    pruned += 1
                continue
            to_fetch.append(code)
        stats = self._fetch_and_upsert(to_fetch)
        result = ProcurementMirrorSyncStats(
            requested=stats.requested,
            upserted=stats.upserted,
            empty_supply=stats.empty_supply,
            http_failed=stats.http_failed,
            pruned=pruned,
        )
        self._log(result)
        return result

    def _linked_codes(self) -> frozenset[str]:
        codes: set[str] = set()
        for number in self._products.numbers():
            product = self._products.get_by_number(number)
            if product is None:
                continue
            if product.catalog_code:
                codes.add(product.catalog_code)
        return frozenset(codes)

    def _fetch_and_upsert(self, codes: Iterable[str]) -> ProcurementMirrorSyncStats:
        code_list = list(codes)
        requested = len(code_list)
        upserted = 0
        empty_supply = 0
        http_failed = 0
        if not code_list:
            return ProcurementMirrorSyncStats(0, 0, 0, 0, 0)

        def work(code: str) -> tuple[str, ProcurementSupplySnapshot | ProcurementFetchFailed]:
            return code, self._fetcher.fetch(code)

        with ThreadPoolExecutor(max_workers=self._supply_concurrency) as pool:
            futures = [pool.submit(work, code) for code in code_list]
            for future in as_completed(futures):
                try:
                    _code, outcome = future.result()
                except Exception:
                    http_failed += 1
                    continue
                if isinstance(outcome, ProcurementFetchFailed):
                    http_failed += 1
                    continue
                mirror = ProcurementMirror(
                    catalog_code=outcome.catalog_code,
                    supplier_id=outcome.supplier_id,
                    supplier_name=outcome.supplier_name,
                    last_buy_price=outcome.last_buy_price,
                    supply_moment=outcome.supply_moment,
                    synced_at=self._clock(),
                    package_quantity=outcome.package_quantity,
                    supplier_product_name=outcome.supplier_product_name,
                )
                self._mirrors.upsert(mirror)
                upserted += 1
                if (
                    outcome.last_buy_price is None
                    and outcome.supplier_id is None
                    and outcome.supply_moment is None
                ):
                    empty_supply += 1
        return ProcurementMirrorSyncStats(
            requested=requested,
            upserted=upserted,
            empty_supply=empty_supply,
            http_failed=http_failed,
            pruned=0,
        )

    def _log(self, stats: ProcurementMirrorSyncStats) -> None:
        _LOGGER.info(
            "procurement_mirror_sync",
            extra={
                "requested": stats.requested,
                "upserted": stats.upserted,
                "empty_supply": stats.empty_supply,
                "http_failed": stats.http_failed,
                "pruned": stats.pruned,
            },
        )


def _zero_stats() -> ProcurementMirrorSyncStats:
    return ProcurementMirrorSyncStats(
        requested=0, upserted=0, empty_supply=0, http_failed=0, pruned=0
    )
