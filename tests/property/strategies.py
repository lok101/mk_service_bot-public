from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import strategies as st

DECIMALS = st.decimals(
    min_value=Decimal("-100000"),
    max_value=Decimal("100000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)
NON_NEGATIVE_DECIMALS = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)
SKU = st.sampled_from(("coffee", "milk", "sugar", "snack"))
SKU_MAPS = st.dictionaries(SKU, DECIMALS, max_size=4)
NON_NEGATIVE_SKU_MAPS = st.dictionaries(SKU, NON_NEGATIVE_DECIMALS, max_size=4)
AWARE_DATETIMES = st.datetimes(
    min_value=datetime(2026, 1, 1),
    max_value=datetime(2026, 12, 31, 23, 59, 59),
    timezones=st.sampled_from((UTC, ZoneInfo("Europe/Moscow"))),
)
TOKEN = st.sampled_from(("id-a", "id-b", "id-c", "id-d"))
POSITIVE_DECIMAL = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("100000"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)
