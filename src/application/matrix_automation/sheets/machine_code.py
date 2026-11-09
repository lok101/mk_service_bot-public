from __future__ import annotations

import re

from beartype import beartype

_VM_CODE_RE = re.compile(r"\[(\d{3})\]")
_PLAIN_CODE_RE = re.compile(r"^\d{3}$")
# Kit UI / API: `[ X ]` / `[ Х ]` (латиница и кириллица) — как sale_monitoring_bot.
_INACTIVE_MARKER_RE = re.compile(r"\[\s*[XxХх]\s*\]")


@beartype
def is_inactive_vending_machine_name(vending_machine_name: str) -> bool:
    """True, если имя содержит marker неактивности `[ X ]` / `[ Х ]` (один X/Х)."""
    return _INACTIVE_MARKER_RE.search(vending_machine_name) is not None


@beartype
def extract_vending_machine_code(vending_machine_name: str) -> str | None:
    match = _VM_CODE_RE.search(vending_machine_name)
    return match.group(1) if match else None


@beartype
def parse_sheet_machine_code(token: str) -> str | None:
    """Parse a single machine code token from matrix sheet H1 (plain or [NNN])."""
    stripped = token.strip()
    if not stripped:
        return None
    bracketed = extract_vending_machine_code(stripped)
    if bracketed is not None:
        return bracketed
    if _PLAIN_CODE_RE.fullmatch(stripped):
        return stripped
    return None
