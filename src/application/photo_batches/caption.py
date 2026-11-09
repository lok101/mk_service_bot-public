from __future__ import annotations

from beartype import beartype

_BOT_MARKER = "🤖 через бота"
_CAPTION_LIMIT = 1024


@beartype
def format_loading_photos_caption(
    *,
    calendar_day_label: str,
    technician_display_name: str,
    machine_display_name: str,
    batch_id: str | None = None,
) -> str:
    header = f"{calendar_day_label} · {technician_display_name} · {machine_display_name}"
    lines = [header, _BOT_MARKER]
    if batch_id:
        debug_line = f"batch: {batch_id}"
        candidate = "\n".join([*lines, debug_line])
        if len(candidate) <= _CAPTION_LIMIT:
            lines.append(debug_line)
    caption = "\n".join(lines)
    if len(caption) > _CAPTION_LIMIT:
        return "\n".join(lines[:2])[:_CAPTION_LIMIT]
    return caption
