from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading import (
    CatalogCard,
    CatalogEnsureError,
    CatalogEnsureLine,
    CommandRejected,
    GroupCandidate,
    LocationCandidate,
    PreflightError,
    PreflightFailed,
    ProductCandidate,
    PublishSnapshotLine,
    ShopCandidate,
    SnapshotStale,
    Synced,
    TemplateRow,
    TemplateWriteFailed,
    ensure_kit_shop_catalog_for_snapshot,
    plan_kit_shop_template_sync,
    prepare_shop_list_write,
)
from src.application.micromarket_loading.publish_job import SyncSnapshotResult
from src.application.micromarket_loading.shop_name import extract_machine_code_from_shop_name
from src.infrastructure.integrations.kitshop.api_models.matrix import (
    KitShopMatrixTemplate,
    KitShopProductGroup,
)
from src.infrastructure.integrations.kitshop.api_models.product import KitShopProduct
from src.infrastructure.integrations.kitshop.api_models.shop import KitShopShop
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopNetworkError,
    KitShopResponseError,
)
from src.infrastructure.rate_limiting import KitShopApiPriority, kitshop_api_priority_scope


@runtime_checkable
class KitShopMatrixApi(Protocol):
    def get_shops(self) -> Sequence[KitShopShop]: ...

    def get_product_groups(self) -> Sequence[KitShopProductGroup]: ...

    def get_products(self) -> Sequence[KitShopProduct]: ...

    def get_product_base_template(self, *, template_id: int) -> KitShopMatrixTemplate: ...

    def add_category_to_product_base_template(
        self,
        *,
        template_id: int,
        category_id: int,
    ) -> None: ...

    def remove_product_from_product_base_template(
        self,
        *,
        template_id: int,
        product_id: int,
    ) -> None: ...

    def add_product_to_product_base_template(
        self,
        *,
        template_id: int,
        product_id: int,
        price_rub: Decimal,
        category_id: int,
        location_id: int,
        disabled: bool = False,
    ) -> None: ...

    def add_command(self, *, shop_id: int) -> None: ...

    def add_product(self, *, vendor_code: str, product_name: str) -> int: ...

    def edit_product_name(self, *, product_id: int, product_name: str) -> None: ...


class _GatewayCatalogWriter:
    def __init__(self, api: KitShopMatrixApi) -> None:
        self._api = api

    def add_product(self, *, vendor_code: str, product_name: str) -> int:
        return self._api.add_product(vendor_code=vendor_code, product_name=product_name)

    def edit_product_name(self, *, product_id: int, product_name: str) -> None:
        self._api.edit_product_name(product_id=product_id, product_name=product_name)


@beartype
class KitShopMatrixGateway:
    def __init__(self, *, api: KitShopMatrixApi, catalog_ensure_enabled: bool = False) -> None:
        self._api = api
        self._catalog_ensure_enabled = catalog_ensure_enabled

    @beartype
    def sync_snapshot(
        self,
        *,
        machine_code: str,
        lines: Sequence[tuple[str, str, int, bool]],
        snapshot_still_current: Callable[[], bool],
        catalog_names: Sequence[tuple[str, str]] = (),
    ) -> SyncSnapshotResult:
        with kitshop_api_priority_scope(KitShopApiPriority.HIGH):
            return self._sync_snapshot_with_priority(
                machine_code=machine_code,
                lines=lines,
                snapshot_still_current=snapshot_still_current,
                catalog_names=catalog_names,
            )

    def _sync_snapshot_with_priority(
        self,
        *,
        machine_code: str,
        lines: Sequence[tuple[str, str, int, bool]],
        snapshot_still_current: Callable[[], bool],
        catalog_names: Sequence[tuple[str, str]],
    ) -> SyncSnapshotResult:
        shops = tuple(
            ShopCandidate(
                shop_id=shop.shop_id,
                shop_name=shop.shop_name,
                template_id=shop.product_base_template_id,
            )
            for shop in self._api.get_shops()
        )
        groups = tuple(
            GroupCandidate(group_id=group.group_id) for group in self._api.get_product_groups()
        )
        raw_products = self._api.get_products()
        if self._catalog_ensure_enabled:
            names = {code: name for code, name in catalog_names}
            ensure_result = ensure_kit_shop_catalog_for_snapshot(
                lines=tuple(
                    CatalogEnsureLine(
                        vendor_code=product_code,
                        domain_name=names.get(product_code, ""),
                    )
                    for product_code, _price, _group, _disabled in lines
                ),
                cards=tuple(
                    CatalogCard(
                        product_id=item.product_id,
                        vendor_code=item.vendor_code or "",
                        product_name=item.product_name,
                        is_deleted=item.is_deleted,
                    )
                    for item in raw_products
                ),
                writer=_GatewayCatalogWriter(self._api),
            )
            if isinstance(ensure_result, CatalogEnsureError):
                return PreflightFailed(message=ensure_result.message)
            raw_products = self._api.get_products()
        products = tuple(
            ProductCandidate(
                product_id=item.product_id,
                vendor_code=item.vendor_code or "",
                is_deleted=item.is_deleted,
            )
            for item in raw_products
        )
        snapshot_lines = tuple(
            PublishSnapshotLine(
                product_code=product_code,
                price_rub=Decimal(price_rub),
                kit_group_id=kit_group_id,
                disabled=disabled,
            )
            for product_code, price_rub, kit_group_id, disabled in lines
        )

        class _NoWrite:
            def add_category(self, *, template_id: int, category_id: int) -> None:
                del template_id, category_id

            def remove_product(self, *, template_id: int, product_id: int) -> None:
                del template_id, product_id

            def add_product(
                self,
                *,
                template_id: int,
                product_id: int,
                price_rub: Decimal,
                category_id: int,
                location_id: int,
                disabled: bool = False,
            ) -> None:
                del template_id, product_id, price_rub, category_id, location_id, disabled

            def add_command(self, *, shop_id: int) -> None:
                del shop_id

        matched_template_id: int | None = None
        for shop in shops:
            if extract_machine_code_from_shop_name(shop.shop_name) == machine_code:
                matched_template_id = shop.template_id
                break
        locations: tuple[LocationCandidate, ...] = ()
        template: KitShopMatrixTemplate | None = None
        if matched_template_id is not None:
            template = self._api.get_product_base_template(template_id=matched_template_id)
            locations = tuple(
                LocationCandidate(
                    location_id=loc.location_id,
                    location_type=loc.location_type,
                )
                for loc in template.locations
            )
        preflight = prepare_shop_list_write(
            machine_code=machine_code,
            shops=shops,
            locations=locations,
            products=products,
            groups=groups,
            lines=snapshot_lines,
            writer=_NoWrite(),
        )
        if isinstance(preflight, PreflightError):
            return PreflightFailed(message=preflight.message)

        assert template is not None
        plan = plan_kit_shop_template_sync(
            desired=preflight.rows,
            current=tuple(
                TemplateRow(
                    product_id=row.product_id,
                    price_rub=row.price,
                    category_id=row.category_id,
                    location_id=row.location_id,
                    disabled=row.disabled,
                )
                for row in template.products
            ),
            category_ids_on_template=tuple(cat.category_id for cat in template.categories),
        )
        try:
            for category_id in plan.add_category_ids:
                self._api.add_category_to_product_base_template(
                    template_id=preflight.template_id,
                    category_id=category_id,
                )
            for product_id in plan.remove_product_ids:
                self._api.remove_product_from_product_base_template(
                    template_id=preflight.template_id,
                    product_id=product_id,
                )
            for row in plan.add_rows:
                self._api.add_product_to_product_base_template(
                    template_id=preflight.template_id,
                    product_id=row.product_id,
                    price_rub=row.price_rub,
                    category_id=row.category_id,
                    location_id=row.location_id,
                    disabled=row.disabled,
                )
        except KitShopResponseError as exc:
            return TemplateWriteFailed(message=str(exc))
        except KitShopNetworkError:
            raise

        if not snapshot_still_current():
            return SnapshotStale()

        try:
            self._api.add_command(shop_id=preflight.shop_id)
        except KitShopResponseError:
            return CommandRejected(message="База товаров на терминал не ушла")
        except KitShopNetworkError:
            raise
        return Synced()
