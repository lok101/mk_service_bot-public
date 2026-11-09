from __future__ import annotations

from enum import IntEnum


class ResultCode(IntEnum):
    SUCCESS = 0
    INVALID_REQUEST_ID = 14
    # PDF Kit Shop API v1.3: FiscalSign format error — not rate limit.
    FISCAL_SIGN_NOT_NUMERIC = 27
