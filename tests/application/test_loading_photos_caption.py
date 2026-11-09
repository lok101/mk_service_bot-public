from __future__ import annotations

from src.application.photo_batches.caption import format_loading_photos_caption


def test_format_loading_photos_caption() -> None:
    caption = format_loading_photos_caption(
        calendar_day_label="05.06.2026",
        technician_display_name="Иванов И.",
        machine_display_name="ТЦ Мега, ряд 2",
    )
    assert caption == "05.06.2026 · Иванов И. · ТЦ Мега, ряд 2\n🤖 через бота"


def test_format_loading_photos_caption_includes_batch_id_when_fits() -> None:
    caption = format_loading_photos_caption(
        calendar_day_label="05.06.2026",
        technician_display_name="Иванов И.",
        machine_display_name="ТЦ Мега",
        batch_id="batch-1",
    )
    assert "batch: batch-1" in caption
