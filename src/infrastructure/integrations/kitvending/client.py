from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, assert_never

import httpx
from beartype import beartype

from src.application.inventory_reconciliation import (
    HOLDING_SKIP_ALERT_SAMPLE_SIZE,
    HoldingSkipSample,
    KitSaleResolveSkip,
    KitSaleResolveSuccess,
    KitVendingFetchStats,
    KitVendingSaleRow,
    RawKitSaleIdentity,
    ReasonClass,
)
from src.application.inventory_reconciliation.sale_skip import (
    MachineSaleSkip,
    SaleSkipReasonClass,
)
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.application.master_data.companies import KitPlatform
from src.application.master_data.company_directory import KitCompanyDirectory
from src.application.product_identity import (
    HOLD_REASON,
    DomainProductResolve,
    ResolveHold,
    ResolveLegacy,
    ResolveRecognized,
    hold_alert_text,
)
from src.domain.machine_sales import SaleKind
from src.infrastructure.integrations.kitvending.api_models.enums import VendingMachineKind
from src.infrastructure.integrations.kitvending.api_models.matrix import MatrixModel
from src.infrastructure.integrations.kitvending.api_models.recipe import RecipeModel
from src.infrastructure.integrations.kitvending.api_models.sale import SaleModel
from src.infrastructure.integrations.kitvending.catalog_cache import (
    CatalogCache,
    CatalogFetchResult,
)
from src.infrastructure.integrations.kitvending.http_client import KitVendingApiClient
from src.infrastructure.integrations.kitvending.parsing.exceptions import (
    SaleProductCodeResolveCriticalError,
    SaleProductCodeResolveNonCriticalError,
)
from src.infrastructure.integrations.kitvending.parsing.sale_resolve import (
    resolve_sale_product_code,
    resolve_sale_vending_machine_code,
)
from src.infrastructure.integrations.kitvending.parsing.utils import (
    compute_vending_machine_type,
    is_product_zero_placeholder,
)
from src.infrastructure.integrations.kitvending.source_id import (
    build_sale_source_id,
    iter_raw_sales_with_source_ids,
)

_LOGGER: Final = logging.getLogger(__name__)

__all__ = ["KitVendingFetchStats", "KitVendingHttpClient"]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
def _sale_kind_from_vending_machine_code(vending_machine_code: str | None) -> SaleKind:
    kind = compute_vending_machine_type(vending_machine_code)
    if kind == VendingMachineKind.SNACK:
        return "snack"
    if kind == VendingMachineKind.COFFEE:
        return "coffee"
    return "unknown"


@beartype
def _machine_key(sale: SaleModel, *, vending_machine_code: str | None = None) -> str:
    if vending_machine_code is not None:
        return vending_machine_code
    code = resolve_sale_vending_machine_code(sale)
    if code is not None:
        return code
    return f"kit_vm:{sale.vending_machine_id}"


@beartype
def _non_holding_reason_class(sale: SaleModel) -> SaleSkipReasonClass:
    if sale.line == -1:
        return "line_neg_1"
    if is_product_zero_placeholder(sale.product_name):
        return "product_zero"
    return "product_zero"


@beartype
@dataclass(frozen=True, slots=True)
class _GatedProductCode:
    product_code: str
    domain_product_id: str


@beartype
@dataclass(frozen=True, slots=True)
class _GatedProductHold:
    detail: str


@beartype
@dataclass
class _FetchStatsAccumulator:
    skipped_unresolved_product: int = 0
    skipped_unresolved_product_non_holding: int = 0
    skipped_no_machine_code: int = 0
    holding: list[HoldingSkipSample] = field(default_factory=list)

    @beartype
    def record_holding(
        self,
        *,
        sale: SaleModel,
        reason_class: ReasonClass,
        machine_key: str,
        detail: str = "",
    ) -> None:
        self.holding.append(
            HoldingSkipSample(
                occurred_at=sale.timestamp.astimezone(UTC),
                reason_class=reason_class,
                machine_key=machine_key,
                vending_machine_name=sale.vending_machine_name,
                matrix_id=sale.matrix_id,
                kit_vending_machine_id=sale.vending_machine_id,
                detail=detail,
            ),
        )


@beartype
@dataclass(slots=True)
class KitVendingHttpClient:
    main_api: KitVendingApiClient
    catalog_fetch: Callable[[], CatalogFetchResult]
    catalog_cache: CatalogCache
    catalog_clients: Sequence[KitVendingApiClient] = ()
    shared_http_client: httpx.Client | None = None
    now: Callable[[], datetime] = _utc_now
    last_fetch_stats: KitVendingFetchStats = field(default_factory=KitVendingFetchStats)
    skip_store: MachineSaleSkipStore | None = None
    company_directory: KitCompanyDirectory | None = None
    _raw_sales_by_source_id: dict[str, SaleModel] = field(default_factory=dict, repr=False)
    _portion_matrices_by_id: dict[int, MatrixModel] | None = field(default=None, repr=False)
    _portion_recipes_by_id: dict[int, RecipeModel] | None = field(default=None, repr=False)
    _portion_matrix_id_by_vm_id: Mapping[int, int] | None = field(default=None, repr=False)
    domain_product_identity_enabled: bool = False
    resolve_sale_code: Callable[[str], DomainProductResolve] | None = None

    @beartype
    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]:
        to_date = until if until is not None else self.now()
        raw_sales = self.main_api.get_sales(from_date=since, to_date=to_date)
        matrices_by_id, recipes_by_id = self.catalog_cache.load(self.catalog_fetch)
        matrix_id_by_vm_id = self.main_api.get_matrix_id_by_vm_id()
        since_utc = since.astimezone(UTC) if since.tzinfo is not None else since.replace(tzinfo=UTC)
        stats = _FetchStatsAccumulator()
        rows: list[KitVendingSaleRow] = []
        for sale in raw_sales:
            row = self._resolve_sale_row(
                sale,
                matrices_by_id=matrices_by_id,
                recipes_by_id=recipes_by_id,
                matrix_id_by_vm_id=matrix_id_by_vm_id,
                since_utc=since_utc,
                stats=stats,
            )
            if row is not None:
                rows.append(row)
        holding = stats.holding
        hold_at = min((sample.occurred_at for sample in holding), default=None)
        fingerprint_pairs = tuple(
            sorted({(sample.machine_key, sample.reason_class) for sample in holding}),
        )
        self.last_fetch_stats = KitVendingFetchStats(
            skipped_unresolved_product=stats.skipped_unresolved_product,
            skipped_unresolved_product_non_holding=stats.skipped_unresolved_product_non_holding,
            skipped_no_machine_code=stats.skipped_no_machine_code,
            holding_skip_count=len(holding),
            hold_at=hold_at,
            holding_samples=tuple(holding[:HOLDING_SKIP_ALERT_SAMPLE_SIZE]),
            fingerprint_pairs=fingerprint_pairs,
        )
        return rows

    @beartype
    def fetch_raw_window(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> list[RawKitSaleIdentity]:
        raw_sales = self.main_api.get_sales(from_date=from_date, to_date=to_date)
        matrices_by_id, recipes_by_id = self.catalog_cache.load(self.catalog_fetch)
        self._portion_matrices_by_id = matrices_by_id
        self._portion_recipes_by_id = recipes_by_id
        self._portion_matrix_id_by_vm_id = self.main_api.get_matrix_id_by_vm_id()
        self._raw_sales_by_source_id = {}
        identities: list[RawKitSaleIdentity] = []
        for sale, source_id in iter_raw_sales_with_source_ids(raw_sales):
            self._raw_sales_by_source_id[source_id] = sale
            identities.append(
                RawKitSaleIdentity(
                    source_id=source_id,
                    kit_vending_machine_id=sale.vending_machine_id,
                    vending_machine_name=sale.vending_machine_name,
                    vending_machine_code=sale.vending_machine_code,
                    occurred_at=sale.timestamp.astimezone(UTC),
                    line_number=sale.line,
                    matrix_id=sale.matrix_id,
                    goods_name=sale.product_name,
                ),
            )
        return identities

    @beartype
    def resolve(self, source_id: str) -> KitSaleResolveSuccess | KitSaleResolveSkip:
        sale = self._raw_sales_by_source_id[source_id]
        if (
            self._portion_matrices_by_id is None
            or self._portion_recipes_by_id is None
            or self._portion_matrix_id_by_vm_id is None
        ):
            raise RuntimeError("fetch_raw_window must be called before resolve")
        return self._classify_sale_for_portion(
            sale,
            matrices_by_id=self._portion_matrices_by_id,
            recipes_by_id=self._portion_recipes_by_id,
            matrix_id_by_vm_id=self._portion_matrix_id_by_vm_id,
        )

    @beartype
    def close(self) -> None:
        if self.shared_http_client is not None:
            self.shared_http_client.close()
        else:
            self.main_api.close()

    @beartype
    def _resolve_mk_company_id(
        self,
        sale: SaleModel,
        *,
        stats: _FetchStatsAccumulator | None,
        machine_key: str,
    ) -> int | None:
        raw_company_id = sale.company_id
        if raw_company_id is None or self.company_directory is None:
            return raw_company_id
        mk_company_id = self.company_directory.resolve(
            KitPlatform.KIT_VENDING,
            raw_company_id,
        )
        if mk_company_id is not None:
            return mk_company_id
        _LOGGER.warning(
            "kit_company_resolve_miss platform=kit_vending kit_company_id=%s sale_source_id=%s",
            raw_company_id,
            build_sale_source_id(sale),
        )
        if stats is not None:
            stats.record_holding(
                sale=sale,
                reason_class="company_unresolved",
                machine_key=machine_key,
            )
        return None

    @beartype
    def _record_skip(self, sale: SaleModel, *, reason_class: SaleSkipReasonClass) -> None:
        if self.skip_store is None:
            return
        seen_at = self.now()
        self.skip_store.upsert(
            MachineSaleSkip(
                source_id=build_sale_source_id(sale),
                reason_class=reason_class,
                kit_vending_machine_id=sale.vending_machine_id,
                vending_machine_name=sale.vending_machine_name,
                occurred_at=sale.timestamp.astimezone(UTC),
                line_number=sale.line,
                matrix_id=sale.matrix_id,
                goods_name=sale.product_name,
                external_id=None,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
        )

    @beartype
    def _gate_domain_product(self, product_code: str) -> _GatedProductCode | _GatedProductHold:
        if not self.domain_product_identity_enabled:
            return _GatedProductCode(product_code=product_code, domain_product_id="")
        resolver = self.resolve_sale_code
        if resolver is None:
            raise ValueError("domain product resolve is required when identity is enabled")
        resolved = resolver(product_code)
        if isinstance(resolved, ResolveRecognized):
            return _GatedProductCode(
                product_code=resolved.catalog_code,
                domain_product_id=resolved.domain_product_id,
            )
        if isinstance(resolved, ResolveLegacy):
            return _GatedProductCode(product_code=product_code, domain_product_id="")
        if isinstance(resolved, ResolveHold):
            reason = HOLD_REASON[resolved.kind]
            text = hold_alert_text(reason)
            _LOGGER.warning(
                "kit_vending_domain_product_hold reason=%s code=%s",
                reason,
                product_code,
            )
            return _GatedProductHold(detail="" if text is None else text)
        assert_never(resolved)

    @beartype
    def _classify_sale_for_portion(
        self,
        sale: SaleModel,
        *,
        matrices_by_id: dict[int, MatrixModel],
        recipes_by_id: dict[int, RecipeModel],
        matrix_id_by_vm_id: Mapping[int, int],
    ) -> KitSaleResolveSuccess | KitSaleResolveSkip:
        try:
            product_code = resolve_sale_product_code(
                sale,
                matrices_by_id,
                recipes_by_id,
                matrix_id_by_vm_id,
            )
        except SaleProductCodeResolveNonCriticalError:
            return KitSaleResolveSkip(
                reason_class=_non_holding_reason_class(sale),
                holding=False,
            )
        except SaleProductCodeResolveCriticalError:
            return KitSaleResolveSkip(
                reason_class="critical_product_resolve",
                holding=True,
            )

        gated = self._gate_domain_product(product_code)
        if isinstance(gated, _GatedProductHold):
            return KitSaleResolveSkip(
                reason_class="critical_product_resolve",
                holding=True,
            )
        product_code = gated.product_code
        domain_product_id = gated.domain_product_id

        vending_machine_code = resolve_sale_vending_machine_code(sale)
        if vending_machine_code is None:
            return KitSaleResolveSkip(
                reason_class="no_machine_code",
                holding=True,
            )

        mk_company_id = self._resolve_mk_company_id(
            sale,
            stats=None,
            machine_key=vending_machine_code,
        )
        if (
            mk_company_id is None
            and sale.company_id is not None
            and self.company_directory is not None
        ):
            return KitSaleResolveSkip(
                reason_class="company_unresolved",
                holding=True,
            )

        return KitSaleResolveSuccess(
            row=KitVendingSaleRow(
                source_id=build_sale_source_id(sale),
                vending_machine_code=vending_machine_code,
                product_code=product_code,
                quantity=Decimal("1"),
                occurred_at=sale.timestamp.astimezone(UTC),
                sale_kind=_sale_kind_from_vending_machine_code(vending_machine_code),
                kit_matrix_id=sale.matrix_id,
                kit_vending_machine_id=sale.vending_machine_id,
                kit_line_number=sale.line,
                price=Decimal(str(sale.price)),
                company_id=mk_company_id,
                domain_product_id=domain_product_id,
            ),
        )

    @beartype
    def _resolve_sale_row(
        self,
        sale: SaleModel,
        *,
        matrices_by_id: dict[int, MatrixModel],
        recipes_by_id: dict[int, RecipeModel],
        matrix_id_by_vm_id: Mapping[int, int],
        since_utc: datetime,
        stats: _FetchStatsAccumulator,
    ) -> KitVendingSaleRow | None:
        try:
            product_code = resolve_sale_product_code(
                sale,
                matrices_by_id,
                recipes_by_id,
                matrix_id_by_vm_id,
            )
        except SaleProductCodeResolveNonCriticalError as exc:
            stats.skipped_unresolved_product += 1
            stats.skipped_unresolved_product_non_holding += 1
            self._record_skip(sale, reason_class=_non_holding_reason_class(sale))
            _LOGGER.debug(
                "Пропуск продажи без кода товара (%s): "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                exc,
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
            )
            return None
        except SaleProductCodeResolveCriticalError as exc:
            stats.skipped_unresolved_product += 1
            stats.record_holding(
                sale=sale,
                reason_class="critical_product_resolve",
                machine_key=_machine_key(sale),
            )
            self._record_skip(sale, reason_class="critical_product_resolve")
            vm_matrix_id = matrix_id_by_vm_id.get(sale.vending_machine_id)
            _LOGGER.warning(
                "Не удалось определить код товара для продажи (%s): "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                exc,
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
                exc_info=True,
                extra={
                    "resolved_via": "vm_current_matrix",
                    "vm_matrix_id": vm_matrix_id,
                    "vending_machine_id": sale.vending_machine_id,
                },
            )
            return None

        gated = self._gate_domain_product(product_code)
        if isinstance(gated, _GatedProductHold):
            stats.skipped_unresolved_product += 1
            stats.record_holding(
                sale=sale,
                reason_class="critical_product_resolve",
                machine_key=_machine_key(sale),
                detail=gated.detail,
            )
            self._record_skip(sale, reason_class="critical_product_resolve")
            return None
        product_code = gated.product_code
        domain_product_id = gated.domain_product_id

        vending_machine_code = resolve_sale_vending_machine_code(sale)
        if vending_machine_code is None:
            stats.skipped_no_machine_code += 1
            stats.record_holding(
                sale=sale,
                reason_class="no_machine_code",
                machine_key=_machine_key(sale),
            )
            self._record_skip(sale, reason_class="no_machine_code")
            _LOGGER.warning(
                "Не удалось определить код аппарата для продажи. "
                "vending_machine_name=%s, line=%s, matrix_id=%s, product_name=%r",
                sale.vending_machine_name,
                sale.line,
                sale.matrix_id,
                sale.product_name,
            )
            return None

        occurred_at = sale.timestamp.astimezone(UTC)
        if occurred_at <= since_utc:
            return None

        mk_company_id = self._resolve_mk_company_id(
            sale,
            stats=stats,
            machine_key=vending_machine_code,
        )
        if (
            mk_company_id is None
            and sale.company_id is not None
            and self.company_directory is not None
        ):
            return None

        return KitVendingSaleRow(
            source_id=build_sale_source_id(sale),
            vending_machine_code=vending_machine_code,
            product_code=product_code,
            quantity=Decimal("1"),
            occurred_at=occurred_at,
            sale_kind=_sale_kind_from_vending_machine_code(vending_machine_code),
            kit_matrix_id=sale.matrix_id,
            kit_vending_machine_id=sale.vending_machine_id,
            kit_line_number=sale.line,
            price=Decimal(str(sale.price)),
            company_id=mk_company_id,
            domain_product_id=domain_product_id,
        )
