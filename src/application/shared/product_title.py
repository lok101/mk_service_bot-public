from __future__ import annotations

from beartype import beartype


@beartype
def product_name_for_lookup(name: str) -> str:
    """Return catalog lookup key segment from form/sheet titles like '🟧 | Концентрат'."""
    stripped = name.strip()
    if "|" not in stripped:
        return stripped
    return stripped.split("|", 1)[1].strip()
