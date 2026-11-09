from __future__ import annotations

import asyncio
import logging

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from .fakes import (
    _FROM,
    _MACHINE_STORE_ID,
    _MAIN_STORE_ID,
    _TECH_STORE_ID,
    _TO,
    _client_with_supply_move,
    _move_row,
    _reader,
    _store_expanded,
    _store_meta_only,
)


def test_reader_resolves_store_codes_from_expand_without_get() -> None:
    """happy: expanded stores с code → move; 0× get_store_code_by_id."""
    client = _client_with_supply_move()
    result = asyncio.run(
        _reader(client).read_moves(
            technician_store_code="tech-1",
            moment_from=_FROM,
            moment_to=_TO,
        ),
    )
    assert [move.document_id for move in result.moves] == ["move-1"]
    assert result.moves[0].source_store_code == "main"
    assert result.moves[0].target_store_code == "tech-1"
    assert client.get_store_code_by_id_calls == []


def test_reader_soft_skips_expanded_store_without_code_no_get() -> None:
    """edge: expanded без code (+ meta-only sibling того же id) → soft-skip, 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "to-machine",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_expanded(_MACHINE_STORE_ID, code=None),
            ),
            # тот же machine id ещё раз как meta-only — не должен триггерить GET
            {
                "id": "sibling-meta",
                "moment": "2026-06-01 13:00:00.000",
                "updated": "2026-06-01 13:00:00.000",
                "sourceStore": _store_expanded(_TECH_STORE_ID, code="tech-1"),
                "targetStore": _store_meta_only(_MACHINE_STORE_ID),
            },
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
    assert result.skipped_unresolved == 2
    assert client.get_store_code_by_id_calls == []


def test_reader_fallback_get_for_meta_only_when_expand_alive() -> None:
    """edge: 1 meta-only среди expanded → ровно 1 GET; soft-resolve map."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
        store_codes_by_id={_TECH_STORE_ID: "tech-1"},
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
    assert client.get_store_code_by_id_calls == [_TECH_STORE_ID]


def test_reader_logs_store_resolve_counters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """happy: info-log stores_expanded / stores_meta_only / store_code_fallback_gets."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_expanded(_MAIN_STORE_ID, code="main"),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
        store_codes_by_id={_TECH_STORE_ID: "tech-1"},
    )
    client.move_positions["move-1"] = [
        {"assortment": {"code": "coffee-rich"}, "quantity": 1},
    ]
    with caplog.at_level(logging.INFO):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    joined = " ".join(record.message for record in caplog.records)
    assert "stores_expanded=1" in joined
    assert "stores_meta_only=1" in joined
    assert "store_code_fallback_gets=1" in joined
