from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from beartype import beartype


@beartype
def path_name_in_scope(path_name: str, *, path_prefix: str, recursive: bool) -> bool:
    if not path_prefix:
        return False
    if path_name == path_prefix:
        return True
    return recursive and path_name.startswith(f"{path_prefix}/")


@beartype
def product_codes_under_path_name(
    rows: Sequence[Mapping[str, Any]],
    *,
    path_prefix: str,
) -> frozenset[str]:
    """Return product codes whose ``pathName`` equals or is under ``path_prefix``."""
    if not path_prefix:
        return frozenset()
    codes: set[str] = set()
    for row in rows:
        path_name = row.get("pathName")
        code = row.get("code")
        if not isinstance(path_name, str) or not isinstance(code, str):
            continue
        normalized = code.strip()
        if not normalized:
            continue
        if path_name_in_scope(path_name, path_prefix=path_prefix, recursive=True):
            codes.add(normalized)
    return frozenset(codes)


@beartype
def food_product_codes_for_cli(
    *,
    handle_food_products: bool,
    ms_configured: bool,
    load_codes: Callable[[], frozenset[str]],
) -> frozenset[str]:
    """Resolve food codes for CLI wiring; skip load when food handling is off."""
    if not handle_food_products or not ms_configured:
        return frozenset()
    return load_codes()
