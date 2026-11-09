from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import pytest
from tests.infrastructure.moysklad.fake_client import FakeMoySkladClient

from src.domain.technician_warehouse.errors import MoySkladUnavailable

from .fakes import (
    _FROM,
    _MAIN_STORE_ID,
    _TECH_STORE_ID,
    _TO,
    _move_row,
    _reader,
    _store_expanded,
    _store_meta_only,
)


def test_reader_raises_when_move_list_store_expand_missing() -> None:
    """error: все store refs meta-only → MoySkladUnavailable, 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_meta_only(_MAIN_STORE_ID),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
        store_codes_by_id={
            _MAIN_STORE_ID: "main",
            _TECH_STORE_ID: "tech-1",
        },
    )
    with pytest.raises(MoySkladUnavailable, match="move list store expand missing"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    assert client.get_store_code_by_id_calls == []


def test_reader_raises_when_excessive_meta_only_store_refs() -> None:
    """error: живой expand + >5 unique meta-only → fail, 0 GET."""
    from src.infrastructure.integrations.moysklad.expand import META_ONLY_FALLBACK_CAP

    meta_only_ids = [
        UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, META_ONLY_FALLBACK_CAP + 2)
    ]
    # один expanded (живой expand) + 6 meta-only unique endpoint ids
    rows: list[dict[str, object]] = [
        _move_row(
            "anchor",
            source=_store_expanded(_MAIN_STORE_ID, code="main"),
            target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
        ),
    ]
    for index, store_id in enumerate(meta_only_ids):
        rows.append(
            _move_row(
                f"meta-{index}",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_meta_only(store_id),
            ),
        )
    client = FakeMoySkladClient(move_rows=rows)
    with pytest.raises(MoySkladUnavailable, match="excessive meta-only store refs"):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    assert client.get_store_code_by_id_calls == []


def test_reader_raises_when_expanded_store_codes_conflict() -> None:
    """error: один store id, два разных непустых code → MoySkladUnavailable, 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "m1",
                source=_store_expanded(_MAIN_STORE_ID, code="main-a"),
                target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
            ),
            _move_row(
                "m2",
                source=_store_expanded(_MAIN_STORE_ID, code="main-b"),
                target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
            ),
        ],
    )
    with pytest.raises(MoySkladUnavailable) as excinfo:
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    message = str(excinfo.value)
    assert "main-a" in message and "main-b" in message
    assert str(_MAIN_STORE_ID) in message
    assert client.get_store_code_by_id_calls == []


def test_reader_logs_store_resolve_counters_before_expand_dead_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """error/observability: expand dead → info-log до raise; 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "move-1",
                source=_store_meta_only(_MAIN_STORE_ID),
                target=_store_meta_only(_TECH_STORE_ID),
            ),
        ],
    )
    with (
        caplog.at_level(logging.INFO),
        pytest.raises(MoySkladUnavailable, match="move list store expand missing"),
    ):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    joined = " ".join(record.message for record in caplog.records)
    assert "stores_expanded=0" in joined
    assert "stores_meta_only=2" in joined
    assert "store_code_fallback_gets=0" in joined
    assert client.get_store_code_by_id_calls == []


def test_reader_logs_store_resolve_counters_before_cap_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """error/observability: cap breach → info-log до raise; 0 GET."""
    from src.infrastructure.integrations.moysklad.expand import META_ONLY_FALLBACK_CAP

    meta_only_ids = [
        UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, META_ONLY_FALLBACK_CAP + 2)
    ]
    rows: list[dict[str, object]] = [
        _move_row(
            "anchor",
            source=_store_expanded(_MAIN_STORE_ID, code="main"),
            target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
        ),
    ]
    for index, store_id in enumerate(meta_only_ids):
        rows.append(
            _move_row(
                f"meta-{index}",
                source=_store_expanded(_TECH_STORE_ID, code="tech-1"),
                target=_store_meta_only(store_id),
            ),
        )
    client = FakeMoySkladClient(move_rows=rows)
    with (
        caplog.at_level(logging.INFO),
        pytest.raises(MoySkladUnavailable, match="excessive meta-only store refs"),
    ):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    joined = " ".join(record.message for record in caplog.records)
    assert "stores_expanded=2" in joined
    assert f"stores_meta_only={META_ONLY_FALLBACK_CAP + 1}" in joined
    assert "store_code_fallback_gets=0" in joined
    assert client.get_store_code_by_id_calls == []


def test_reader_logs_store_resolve_counters_before_conflict_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """error/observability: conflict codes → info-log до raise; 0 GET."""
    client = FakeMoySkladClient(
        move_rows=[
            _move_row(
                "m1",
                source=_store_expanded(_MAIN_STORE_ID, code="main-a"),
                target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
            ),
            _move_row(
                "m2",
                source=_store_expanded(_MAIN_STORE_ID, code="main-b"),
                target=_store_expanded(_TECH_STORE_ID, code="tech-1"),
            ),
        ],
    )
    with (
        caplog.at_level(logging.INFO),
        pytest.raises(MoySkladUnavailable) as excinfo,
    ):
        asyncio.run(
            _reader(client).read_moves(
                technician_store_code="tech-1",
                moment_from=_FROM,
                moment_to=_TO,
            ),
        )
    message = str(excinfo.value)
    assert "main-a" in message and "main-b" in message
    joined = " ".join(record.message for record in caplog.records)
    assert "stores_expanded=2" in joined
    assert "stores_meta_only=0" in joined
    assert "store_code_fallback_gets=0" in joined
    assert client.get_store_code_by_id_calls == []
