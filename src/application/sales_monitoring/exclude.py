from __future__ import annotations

from collections.abc import Sequence

from beartype import beartype


@beartype
def parse_excluded_machine_codes(raw: str | Sequence[str]) -> frozenset[str]:
    """Trim CSV / sequence items and drop empties for detection exclude set."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    return frozenset(item.strip() for item in items if item.strip())


@beartype
def union_excluded_machine_codes(*parts: frozenset[str]) -> frozenset[str]:
    merged: set[str] = set()
    for part in parts:
        merged.update(part)
    return frozenset(merged)
