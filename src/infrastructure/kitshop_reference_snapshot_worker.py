from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol, runtime_checkable

from beartype import beartype

from src.infrastructure.integrations.kitshop.api_models.matrix import KitShopProductGroup
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshot,
    KitShopReferenceSnapshotStore,
    KitShopSnapshotGroup,
    KitShopSnapshotProduct,
    KitShopSnapshotShop,
)

_LOGGER: Final = logging.getLogger(__name__)


@runtime_checkable
class KitShopReferenceSnapshotApi(Protocol):
    @property
    def account(self) -> object: ...

    def get_product_groups(self) -> Sequence[KitShopProductGroup]: ...

    def get_shops(self) -> Sequence[KitShopShop]: ...

    def get_products(self) -> Sequence[KitShopProduct]: ...


@beartype
@dataclass(slots=True)
class KitShopReferenceSnapshotWorker:
    store: KitShopReferenceSnapshotStore
    api: KitShopReferenceSnapshotApi
    refresh_interval_seconds: float

    @beartype
    def refresh_once(self) -> None:
        started = time.perf_counter()
        kit_company_id = int(self.api.account.kit_company_id)  # type: ignore[attr-defined]
        phase = "GetProductGroups"
        try:
            groups = self.api.get_product_groups()
            phase = "GetShops"
            shops = self.api.get_shops()
            phase = "GetProducts"
            products = self.api.get_products()
        except Exception as exc:
            previous = self.store.get(kit_company_id)
            age_seconds: float | None = None
            if previous is not None:
                age_seconds = (
                    datetime.now(tz=UTC) - previous.refreshed_at.astimezone(UTC)
                ).total_seconds()
            _LOGGER.warning(
                "kitshop_reference_snapshot_refresh_failed",
                extra={
                    "phase": phase,
                    "exception_type": type(exc).__name__,
                    "kit_company_id": kit_company_id,
                    "previous_age_seconds": age_seconds,
                },
            )
            raise

        refreshed_at = datetime.now(tz=UTC)
        snapshot = KitShopReferenceSnapshot(
            kit_company_id=kit_company_id,
            refreshed_at=refreshed_at,
            groups=tuple(
                KitShopSnapshotGroup(group_id=g.group_id, group_name=g.group_name) for g in groups
            ),
            shops=tuple(
                KitShopSnapshotShop(
                    shop_id=s.shop_id,
                    shop_name=s.shop_name,
                    product_base_template_id=s.product_base_template_id,
                )
                for s in shops
            ),
            products=tuple(
                KitShopSnapshotProduct(
                    product_id=p.product_id,
                    vendor_code=p.vendor_code,
                    product_name=p.product_name,
                    is_deleted=p.is_deleted,
                )
                for p in products
            ),
        )
        self.store.replace(snapshot)
        _LOGGER.info(
            "kitshop_reference_snapshot_refreshed",
            extra={
                "kit_company_id": kit_company_id,
                "refreshed_at": refreshed_at.isoformat(),
                "groups_count": len(snapshot.groups),
                "shops_count": len(snapshot.shops),
                "products_count": len(snapshot.products),
                "duration_seconds": round(time.perf_counter() - started, 3),
            },
        )

    @beartype
    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.to_thread(self.refresh_once)
            except Exception:
                _LOGGER.exception("kitshop_reference_snapshot_worker_cycle_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.refresh_interval_seconds,
                )


__all__ = ["KitShopReferenceSnapshotApi", "KitShopReferenceSnapshotWorker"]
