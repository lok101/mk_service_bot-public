from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.master_data import MasterDataAuditRecord, MasterDataStores
from src.application.matrix_automation.ports import MatrixBaseMarginStore
from src.domain.matrix_pricing.formula import BaseMarginParams


class BaseMarginCommandRejected(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
def validate_base_margin_params(
    params: BaseMarginParams,
    *,
    scale_price_min_bound: Decimal,
    scale_price_max_bound: Decimal,
    scale_rate_min_bound: Decimal,
    scale_rate_max_bound: Decimal,
    curvature_min: Decimal,
    curvature_max: Decimal,
    margin_floor_min: Decimal,
    margin_floor_max: Decimal,
) -> None:
    if not (
        scale_price_min_bound
        <= params.scale_price_min
        < params.scale_price_max
        <= scale_price_max_bound
    ):
        raise BaseMarginCommandRejected(
            "scale_price out of bounds or unordered",
            code="scale_price_out_of_bounds",
        )
    if not (
        scale_rate_min_bound
        <= params.scale_rate_min
        <= params.scale_rate_max
        <= scale_rate_max_bound
    ):
        raise BaseMarginCommandRejected(
            "scale_rate out of bounds or unordered",
            code="scale_rate_out_of_bounds",
        )
    if not (curvature_min <= params.curvature <= curvature_max):
        raise BaseMarginCommandRejected(
            "curvature out of bounds",
            code="curvature_out_of_bounds",
        )
    if not (margin_floor_min <= params.margin_floor <= margin_floor_max):
        raise BaseMarginCommandRejected(
            "margin_floor out of bounds",
            code="margin_floor_out_of_bounds",
        )


@beartype
@dataclass(slots=True)
class SaveBaseMargin:
    store: MatrixBaseMarginStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    scale_price_min_bound: Decimal
    scale_price_max_bound: Decimal
    scale_rate_min_bound: Decimal
    scale_rate_max_bound: Decimal
    curvature_min: Decimal
    curvature_max: Decimal
    margin_floor_min: Decimal
    margin_floor_max: Decimal

    @beartype
    def execute(self, *, params: BaseMarginParams, actor_telegram_user_id: int) -> None:
        validate_base_margin_params(
            params,
            scale_price_min_bound=self.scale_price_min_bound,
            scale_price_max_bound=self.scale_price_max_bound,
            scale_rate_min_bound=self.scale_rate_min_bound,
            scale_rate_max_bound=self.scale_rate_max_bound,
            curvature_min=self.curvature_min,
            curvature_max=self.curvature_max,
            margin_floor_min=self.margin_floor_min,
            margin_floor_max=self.margin_floor_max,
        )
        self.store.save(params)
        rounding = params.rounding_last_digits
        rounding_payload = (
            "" if rounding is None else ",".join(str(digit) for digit in sorted(rounding))
        )
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=actor_telegram_user_id,
                command="save_matrix_base_margin",
                payload={
                    "scale_price_min": str(params.scale_price_min),
                    "scale_price_max": str(params.scale_price_max),
                    "scale_rate_max": str(params.scale_rate_max),
                    "scale_rate_min": str(params.scale_rate_min),
                    "curvature": str(params.curvature),
                    "margin_floor": str(params.margin_floor),
                    "rounding_last_digits": rounding_payload,
                },
            )
        )
