from __future__ import annotations

from types import SimpleNamespace

from beartype import beartype

from src.domain.form_submission import FrozenInventoryLine


@beartype
def residual_pre_loading_purpose_snapshot(
    *,
    validated_lines: tuple[FrozenInventoryLine, ...],
) -> SimpleNamespace:
    """Stub snapshot with residual purpose after R2 Literal cut (beartype-safe)."""
    return SimpleNamespace(purpose="pre_loading", validated_lines=validated_lines)
