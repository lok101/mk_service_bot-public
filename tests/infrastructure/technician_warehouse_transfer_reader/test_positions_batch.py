from __future__ import annotations

import asyncio

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.domain.technician_warehouse.errors import MoySkladUnavailable
from src.infrastructure.integrations.moysklad.exceptions import MoySkladError
from src.infrastructure.integrations.moysklad.expand import EXPAND_MAX_LIMIT

from .fakes import (
    _FROM,
    _MAIN_STORE_ID,
    _TO,
    _client_with_supply_move,
    _move_row,
    _reader,
    _store_expanded,
)


def test_reader_batches_positions_without_per_move_get() -> None:
    # happy: N tech-relevant moves → one get_moves_by_ids, zero get_move_positions
    client = FakeMoySkladClient(
        move_rows=[_move_row("move-1"), _move_row("move-2"), _move_row("move-3")],
    )
    for move_id in ("move-1", "move-2", "move-3"):
        client.move_positions[move_id] = [
            {"assortment": {"code": f"sku-{move_id}"}, "quantity": 1},
        ]

    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )

    assert [move.document_id for move in result.moves] == ["move-1", "move-2", "move-3"]
    assert client.get_moves_by_ids_calls == [("move-1", "move-2", "move-3")]
    assert client.get_move_positions_calls == []


def test_reader_chunks_batch_when_ids_exceed_expand_limit() -> None:
    # happy: >EXPAND_MAX_LIMIT tech moves → multiple batch GETs, still no per-move
    move_ids = tuple(f"move-{index}" for index in range(EXPAND_MAX_LIMIT + 2))
    client = FakeMoySkladClient(move_rows=[_move_row(move_id) for move_id in move_ids])
    for move_id in move_ids:
        client.move_positions[move_id] = [
            {"assortment": {"code": "coffee"}, "quantity": 1},
        ]

    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )

    assert len(result.moves) == len(move_ids)
    assert len(client.get_moves_by_ids_calls) == 1  # fake receives full tuple once
    # Real client chunks; fake gets one call with all ids from reader.
    # Reader passes full id tuple to client.get_moves_by_ids — client chunks.
    assert client.get_move_positions_calls == []


def test_reader_empty_filtered_set_skips_batch() -> None:
    # edge: no tech-relevant moves → no batch positions fetch
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "other-move",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_expanded(_MAIN_STORE_ID, code="main"),
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
    assert client.get_moves_by_ids_calls == []
    assert client.get_move_positions_calls == []


def test_reader_positions_expand_dead_fails_closed() -> None:
    # error: batch row without expanded positions.rows → MoySkladUnavailable
    client = _client_with_supply_move()

    async def _dead_expand(*, move_ids: tuple[str, ...]) -> list[dict[str, object]]:
        return [{"id": move_id, "positions": {"meta": {"href": "x"}}} for move_id in move_ids]

    client.get_moves_by_ids = _dead_expand  # type: ignore[method-assign]

    with pytest.raises(MoySkladUnavailable, match="positions expand dead"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )


def test_reader_batch_http_error_fails_closed() -> None:
    # error: batch GET raises → MoySkladUnavailable
    client = _client_with_supply_move()
    client.get_moves_by_ids_error = MoySkladError("batch unavailable")

    with pytest.raises(MoySkladUnavailable, match="batch unavailable"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )


def test_reader_falls_back_to_paginated_positions_when_expand_truncated() -> None:
    # edge: meta.size > expanded rows → paginated get_move_positions for that move
    client = FakeMoySkladClient(move_rows=[_move_row("move-1")])
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
    assert client.get_moves_by_ids_calls == [("move-1",)]
    assert client.get_move_positions_calls  # paginated fallback used
    assert "move-1" in client.get_move_positions_calls
