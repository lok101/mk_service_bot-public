from __future__ import annotations

from typing import Any


class MoySkladError(Exception):
    pass


class MoySkladValidationError(MoySkladError):
    pass


class MoySkladConnectionError(MoySkladError):
    pass


class MoySkladAPIError(MoySkladError):
    pass


class MoySkladRequestError(MoySkladAPIError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        self.codes = _extract_error_codes(payload)
        codes_repr = self.codes if self.codes else "none"
        super().__init__(f"MoySklad HTTP {status}: codes={codes_repr}")

    @property
    def code(self) -> int | None:
        return self.codes[0] if self.codes else None


def _extract_error_codes(payload: dict[str, Any]) -> list[int]:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return []
    out: list[int] = []
    for item in errors:
        if isinstance(item, dict):
            code = item.get("code")
            if isinstance(code, int):
                out.append(code)
    return out
