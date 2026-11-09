from __future__ import annotations

import asyncio

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.integrations.moysklad.exceptions import (
    MoySkladError,
    MoySkladValidationError,
)

from .fakes import (
    _FROM,
    _MACHINE_STORE_ID,
    _MAIN_STORE_ID,
    _OTHER_TECH_STORE_ID,
    _TECH_STORE_ID,
    _TO,
    _move_row,
    _reader,
    _store_expanded,
    _store_meta_only,
)


def test_reader_returns_tech_move_when_window_has_store_without_code() -> None:
    """happy: в окне move без code + supply↔tech → tech move, без raise; 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "machine-move",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_expanded(_MACHINE_STORE_ID, code=None),
            ),
            _move_row("supply-move"),
        ],
    )
    client.move_positions["supply-move"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert [move.document_id for move in result.moves] == ["supply-move"]
    assert result.skipped_unresolved == 1
    assert client.get_store_code_by_id_calls == []


def test_reader_soft_skips_move_when_store_has_no_code() -> None:
    """edge: tech↔store без code → skip + skipped_unresolved, не raise; 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "to-machine",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_expanded(_MACHINE_STORE_ID, code=None),
            ),
        ],
    )
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert result.moves == ()
    assert result.skipped_unresolved == 1
    assert client.get_store_code_by_id_calls == []


def test_reader_soft_skips_move_when_store_code_is_blank() -> None:
    """edge: expanded whitespace code → не в map, soft-skip; 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "to-machine",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_expanded(_MACHINE_STORE_ID, code="   "),
            ),
        ],
    )
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert result.moves == ()
    assert result.skipped_unresolved == 1
    assert client.get_store_code_by_id_calls == []


def test_reader_skips_non_technician_move_without_skipped_unresolved() -> None:
    """edge: оба code есть, нет technician_store_code → skip без skipped_unresolved."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "other-tech",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_expanded(_OTHER_TECH_STORE_ID, code="tech-other"),
            ),
        ],
    )
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert result.moves == ()
    assert result.skipped_unresolved == 0


def test_reader_raises_when_store_get_http_error() -> None:
    """error: HTTP на fallback GET meta-only → MoySkladUnavailable."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
        store_code_errors_by_id={
            _TECH_STORE_ID: MoySkladError("MS store GET failed"),
        },
    )
    with pytest.raises(MoySkladUnavailable, match="MS store GET failed"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    assert client.get_store_code_by_id_calls == [_TECH_STORE_ID]


def test_reader_raises_when_store_validation_is_not_missing_code() -> None:
    """error: MoySkladValidationError без «has no code» на fallback → MoySkladUnavailable."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
        store_code_errors_by_id={
            _TECH_STORE_ID: MoySkladValidationError(
                f"Store {_TECH_STORE_ID} response is invalid.",
            ),
        },
    )
    with pytest.raises(MoySkladUnavailable, match="invalid"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    assert client.get_store_code_by_id_calls == [_TECH_STORE_ID]
