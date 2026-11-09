from __future__ import annotations

import pytest

from src.application.matrix_automation.sheets.machine_code import (
    extract_vending_machine_code,
    is_inactive_vending_machine_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "[ X ] [150] - Кола",  # happy: пробелы вокруг латинского X
        "[X] [150]",  # edge: без пробелов
        "[ x ] [150]",  # edge: нижний регистр латиницы
        "[\tX ] [150]",  # edge: таб как whitespace
        "Аппарат [150] [ X ]",  # edge: marker в конце строки
        "[ Х ] [150] - Кола",  # happy: кириллическая Х (Kit UI)
        "[Х] [150]",  # edge: кириллица без пробелов
        "[ х ] [150]",  # edge: кириллица lower
    ],
)
def test_is_inactive_true_for_marker_variants(name: str) -> None:
    assert is_inactive_vending_machine_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "[150] - Кола",  # happy: активный
        "[XX] [150]",  # edge: два X — не marker
        "[X X] [150]",  # edge: X пробел X — не marker
        "[ ХХ ] [150]",  # edge: две кириллические Х — не marker
        "Аппарат без маркера",  # edge: нет скобок
    ],
)
def test_is_inactive_false_for_non_marker(name: str) -> None:
    assert is_inactive_vending_machine_name(name) is False


def test_extract_vending_machine_code_still_parses_inactive_name() -> None:
    # regression: код извлекается и из неактивного имени (historical sales)
    assert extract_vending_machine_code("[ X ] [150] - Кола") == "150"
    assert extract_vending_machine_code("[ Х ] [150] - Кола") == "150"
    assert extract_vending_machine_code("[150] - Кола") == "150"


def test_is_inactive_exported_via_public_surface() -> None:
    from src.application.matrix_automation import is_inactive_vending_machine_name as exported

    assert exported("[ X ] [150]") is True
    assert exported("[ Х ] [150]") is True
