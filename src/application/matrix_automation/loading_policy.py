from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.domain.matrix_pricing import detect_pending_product_swap


@beartype
@dataclass(frozen=True, slots=True)
class DefaultMatrixCellLoadingPolicy:
    @beartype
    def is_loading_blocked(
        self,
        *,
        desired_product: str | None,
        snapshot_product: str | None,
    ) -> bool:
        return detect_pending_product_swap(
            desired_product=desired_product,
            snapshot_product=snapshot_product,
        )
