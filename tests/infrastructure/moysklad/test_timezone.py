from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.infrastructure.integrations.moysklad.exceptions import MoySkladValidationError
from src.infrastructure.integrations.moysklad.timezone import format_moment


def test_format_moment_converts_utc_to_msk_string() -> None:
    moment = datetime(2026, 5, 20, 8, 0, tzinfo=UTC)
    assert format_moment(moment) == "2026-05-20 11:00:00"


def test_format_moment_rejects_naive_datetime() -> None:
    with pytest.raises(MoySkladValidationError, match="tz"):
        format_moment(datetime(2026, 5, 20, 11, 0))
