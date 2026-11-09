from __future__ import annotations

import html

from beartype import beartype

from src.domain.event_reminders.parse import BadRow, ParsedEventRow

BLOCK_SEPARATOR = "\n\n\n"
TELEGRAM_HTML_MESSAGE_MAX = 4096
_HTML_PRE_WRAPPER_LEN = len("<pre></pre>")
# Max plain content length such that `<pre>` + html.escape(content) + `</pre>` ≤ 4096.
TELEGRAM_PRE_PLAIN_MAX = TELEGRAM_HTML_MESSAGE_MAX - _HTML_PRE_WRAPPER_LEN


@beartype
def telegram_pre_content_len(text: str) -> int:
    """Length after html.escape — what occupies space inside <pre>...</pre>."""
    return len(html.escape(text))


@beartype
def format_event_block(event: ParsedEventRow) -> str:
    date_str = event.event_date.strftime("%d.%m.%y")
    return (
        f"{'🔻' * 8}\n"
        f"Дата: {date_str}\n"
        f"Локация: {event.location}\n"
        f"\n"
        f"<<{event.comment}>>\n"
        f"{'🔺' * 8}"
    )


@beartype
def join_event_blocks(blocks: tuple[str, ...]) -> str:
    return BLOCK_SEPARATOR.join(blocks)


@beartype
def chunk_plain_blocks_with_skips(
    blocks: tuple[str, ...],
    *,
    max_plain_len: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Pack whole event blocks; oversized single blocks go to skipped.

    Length checks use html.escape so chunking matches Telegram HTML <pre> payload.
    """
    chunks: list[str] = []
    skipped: list[str] = []
    current: list[str] = []
    current_len = 0
    sep_len = telegram_pre_content_len(BLOCK_SEPARATOR)

    for block in blocks:
        block_len = telegram_pre_content_len(block)
        if block_len > max_plain_len:
            if current:
                chunks.append(join_event_blocks(tuple(current)))
                current = []
                current_len = 0
            skipped.append(block)
            continue

        added = (sep_len if current else 0) + block_len
        if current and current_len + added > max_plain_len:
            chunks.append(join_event_blocks(tuple(current)))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += added

    if current:
        chunks.append(join_event_blocks(tuple(current)))
    return tuple(chunks), tuple(skipped)


@beartype
def chunk_plain_blocks(
    blocks: tuple[str, ...],
    *,
    max_plain_len: int,
) -> tuple[str, ...]:
    chunks, _skipped = chunk_plain_blocks_with_skips(blocks, max_plain_len=max_plain_len)
    return chunks


@beartype
def format_bad_rows_summary(bad_rows: tuple[BadRow, ...], *, max_len: int) -> str:
    if not bad_rows:
        return ""
    header = f"Битые строки ({len(bad_rows)}):\n"
    lines = [f"{row.row_number} → {row.preview}" for row in bad_rows]
    full = header + "\n".join(lines)
    if len(full) <= max_len:
        return full

    included = 0
    for count in range(1, len(lines) + 1):
        rest = len(lines) - count
        body = "\n".join(lines[:count])
        text = header + body + (f"\n…и ещё {rest}" if rest > 0 else "")
        if len(text) <= max_len:
            included = count
        else:
            break

    if included == 0:
        rest = len(lines) - 1
        suffix = f"\n…и ещё {rest}" if rest > 0 else ""
        budget = max_len - len(header) - len(suffix)
        if budget < 1:
            return (header + f"…и ещё {len(lines)}")[:max_len]
        return header + lines[0][:budget] + suffix

    rest = len(lines) - included
    body = "\n".join(lines[:included])
    return header + body + (f"\n…и ещё {rest}" if rest > 0 else "")
