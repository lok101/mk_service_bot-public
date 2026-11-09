from __future__ import annotations

from beartype import beartype


@beartype
def inventory_qty_validation_upper(qty_max: int) -> int:
    """Inclusive upper bound for inventory qty (webhook / domain SoT).

    Google Forms REST cannot attach number validation to ``textQuestion``; UI
    validators are not emitted. Cap is enforced on accept after parse.
    """
    if qty_max < 0:
        raise ValueError("qty_max must be >= 0")
    return qty_max
