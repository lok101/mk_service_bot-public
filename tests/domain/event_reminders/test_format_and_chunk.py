from __future__ import annotations

from datetime import date

from src.domain.event_reminders.format_message import (
    chunk_plain_blocks,
    chunk_plain_blocks_with_skips,
    format_bad_rows_summary,
    format_event_block,
    join_event_blocks,
)
from src.domain.event_reminders.parse import BadRow, ParsedEventRow


def test_format_block_empty_comment() -> None:
    text = format_event_block(ParsedEventRow(date(2026, 7, 29), "Лыжная база", ""))
    assert "Дата: 29.07.26" in text
    assert "Локация: Лыжная база" in text
    assert "<<>>" in text
    assert text.startswith("🔻" * 8)
    assert text.endswith("🔺" * 8)


def test_join_three_blank_lines() -> None:
    a = format_event_block(ParsedEventRow(date(2026, 7, 29), "A", "1"))
    b = format_event_block(ParsedEventRow(date(2026, 7, 30), "B", "2"))
    joined = join_event_blocks((a, b))
    assert "\n\n\n" in joined
    assert joined.index(a) < joined.index(b)


def test_chunk_splits_on_event_boundary() -> None:
    blocks = tuple(
        format_event_block(ParsedEventRow(date(2026, 7, 29), f"L{i}", "c" * 20)) for i in range(5)
    )
    chunks = chunk_plain_blocks(blocks, max_plain_len=200)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert "🔻" in chunk


def test_oversized_single_event_skipped() -> None:
    huge = format_event_block(ParsedEventRow(date(2026, 7, 29), "L", "x" * 5000))
    chunks, skipped = chunk_plain_blocks_with_skips((huge,), max_plain_len=100)
    assert chunks == ()
    assert skipped == (huge,)


def test_chunk_skips_when_html_escape_exceeds_limit() -> None:
    # Plain len fits; after escape (& → &amp;) the block exceeds max_plain_len.
    block = format_event_block(ParsedEventRow(date(2026, 7, 29), "L", "&" * 40))
    assert len(block) <= 200
    chunks, skipped = chunk_plain_blocks_with_skips((block,), max_plain_len=200)
    assert chunks == ()
    assert skipped == (block,)


def test_bad_rows_summary_truncates_with_and_more() -> None:
    bad = tuple(BadRow(row_number=i, preview="x" * 80) for i in range(1, 40))
    text = format_bad_rows_summary(bad, max_len=500)
    assert "…и ещё" in text or "...и ещё" in text
    assert len(text) <= 500
