from __future__ import annotations

from src.application.sales_monitoring.exclude import (
    parse_excluded_machine_codes,
    union_excluded_machine_codes,
)


def test_parse_excluded_codes_trims_and_drops_empty() -> None:
    assert parse_excluded_machine_codes(" A1, , B2,,") == frozenset({"A1", "B2"})


def test_parse_excluded_codes_empty_string() -> None:
    assert parse_excluded_machine_codes("") == frozenset()


def test_union_excluded_codes_merges_csv_and_ui() -> None:
    assert union_excluded_machine_codes(
        frozenset({"A1"}),
        frozenset({"B2", "A1"}),
    ) == frozenset({"A1", "B2"})
