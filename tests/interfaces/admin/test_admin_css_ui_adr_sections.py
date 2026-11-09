from __future__ import annotations

from pathlib import Path

_CSS = Path("src/interfaces/admin/static/admin.css")

_CORE_MARKERS = (
    "/* === tokens === */",
    "/* === shell === */",
    "/* === UI-ADR-0019 admin-app-sidebar === */",
    "/* === UI-ADR-0018 admin-app-header === */",
    "/* === UI-ADR-0016 admin-link === */",
    "/* === UI-ADR-0020 admin-save-bar === */",
    "/* === UI-ADR-0013 admin-data-table === */",
    "/* === UI-ADR-0043 admin-quantity-stepper === */",
    "/* === misc === */",
)


def test_admin_css_defines_ui_adr_section_markers() -> None:
    # happy: ядро якорей UI-ADR chrome присутствует в admin.css
    css = _CSS.read_text(encoding="utf-8")
    missing = [marker for marker in _CORE_MARKERS if marker not in css]
    assert missing == [], f"missing section markers: {missing}"
