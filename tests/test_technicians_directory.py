from __future__ import annotations

import pytest

from src.application.sheets.technicians_directory import (
    build_technicians_directory_snapshot,
)
from src.domain.ids import TechnicianId

_HEADER = ["active", "Id", "Имя"]


def test_parse_technicians_directory_happy() -> None:
    snap = build_technicians_directory_snapshot(
        [_HEADER, ["TRUE", "10003", "Данил"], ["FALSE", "10017", "Егор"]],
    )
    assert snap.names_by_id[TechnicianId("10003")] == "Данил"
    assert snap.names_by_id[TechnicianId("10017")] == "Егор"
    assert "active_by_id" not in snap.__dataclass_fields__


def test_parse_ignores_active_column() -> None:
    snap = build_technicians_directory_snapshot(
        [_HEADER, ["FALSE", "10003", "Данил"]],
    )
    assert snap.names_by_id[TechnicianId("10003")] == "Данил"


def test_parse_duplicate_id_fails() -> None:
    with pytest.raises(ValueError, match="[Dd]uplicate|[Ii]d"):
        build_technicians_directory_snapshot(
            [_HEADER, ["TRUE", "10003", "Данил"], ["TRUE", "10003", "Данил"]],
        )


def test_parse_empty_directory_fails() -> None:
    with pytest.raises(ValueError, match="empty|no .*id"):
        build_technicians_directory_snapshot([_HEADER])


def test_parse_requires_id_and_name_headers() -> None:
    with pytest.raises(ValueError, match=r"(?i)id|имя|header"):
        build_technicians_directory_snapshot([["Id"], ["10003"]])
