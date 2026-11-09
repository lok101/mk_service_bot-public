from __future__ import annotations

import asyncio

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.application.technician_warehouse.ports import ReadMovesResult
from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.integrations.moysklad.exceptions import MoySkladError

from .fakes import (
    _FROM,
    _MAIN_STORE_ID,
    _TO,
    _client_with_supply_move,
    _move_row,
    _reader,
    _store_expanded,
)


def test_reader_returns_read_moves_result_with_skipped_unresolved() -> None:
    client = _client_with_supply_move()
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert isinstance(result, ReadMovesResult)
    assert [move.document_id for move in result.moves] == ["move-1"]
    assert result.skipped_unresolved == 0


def test_reader_lists_moves_in_requested_window() -> None:
    client = FakeMoySkladClient(
        move_rows=[_move_row("move-1")],
    )
    client.move_positions["move-1"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert [move.document_id for move in result.moves] == ["move-1"]
    assert client.move_list_calls == [(_FROM, _TO)]


def test_reader_fetches_positions_and_store_codes() -> None:
    client = _client_with_supply_move()
    move = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    ).moves[0]
    assert (move.source_store_code, move.target_store_code) == ("main", "tech-1")
    assert move.lines[0].product_code == "coffee-rich"


def test_reader_returns_empty_tuple_when_no_moves() -> None:
    result = asyncio.run(
        _reader(FakeMoySkladClient()).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert result.moves == ()
    assert result.skipped_unresolved == 0


def test_reader_propagates_moysklad_http_error() -> None:
    client = FakeMoySkladClient(move_list_error=MoySkladError("MS unavailable"))
    with pytest.raises(MoySkladUnavailable, match="MS unavailable"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )


def test_reader_skips_moves_not_involving_technician_store() -> None:
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "other-move",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_expanded(_MAIN_STORE_ID, code="main"),
            ),
            _move_row("tech-move"),
        ],
    )
    client.move_positions["tech-move"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert [move.document_id for move in result.moves] == ["tech-move"]


def test_reader_fetches_all_paginated_move_positions() -> None:
    client = FakeMoySkladClient(
        move_rows=[_move_row("move-1")],
    )
    client.move_positions["move-1"] = [
        {"assortment": {"code": f"sku-{index}"}, "quantity": 1} for index in range(101)
    ]
    move = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    ).moves[0]
    assert len(move.lines) == 101
    assert move.lines[0].product_code == "sku-0"
    assert move.lines[-1].product_code == "sku-100"


def test_reader_surfaces_applicable_false_on_external_move() -> None:
    client = FakeMoySkladClient(move_rows=[_move_row("unposted-move", applicable=False)])
    client.move_positions["unposted-move"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    move = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    ).moves[0]
    assert move.document_id == "unposted-move"
    assert move.applicable is False


def test_reader_defaults_missing_applicable_to_true() -> None:
    row = _move_row("legacy-move")
    del row["applicable"]
    client = FakeMoySkladClient(move_rows=[row])
    client.move_positions["legacy-move"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    move = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    ).moves[0]
    assert move.applicable is True
