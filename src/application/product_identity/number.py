from __future__ import annotations

import re

from beartype import beartype

_CANONICAL_NUMBER = re.compile(r"d-\d+")


@beartype
def canonical_domain_number(raw: str) -> str | None:
    trimmed = raw.strip()
    folded = "d" + trimmed[1:] if trimmed[:1] in {"d", "D"} else trimmed
    if _CANONICAL_NUMBER.fullmatch(folded) is None:
        return None
    return folded


@beartype
def catalog_code_key(code: str) -> str:
    trimmed = code.strip()
    if trimmed[:1] in {"d", "D"}:
        return "d" + trimmed[1:]
    return trimmed
