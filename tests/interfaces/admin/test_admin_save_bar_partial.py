from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from tests.interfaces.admin.test_admin_auth_routes import _build_app, _signed_widget_fields

from src.interfaces.admin.http_common import TEMPLATES

_TEMPLATES_ROOT = Path("src/interfaces/admin/templates")
_MACRO = _TEMPLATES_ROOT / "_admin_save_bar.html"
_SHELL_CLASS = 'class="admin-save-bar"'


def test_save_bar_shell_class_lives_only_in_macro() -> None:
    assert _SHELL_CLASS in _MACRO.read_text(encoding="utf-8")
    offenders = [
        path.as_posix()
        for path in _TEMPLATES_ROOT.glob("*.html")
        if path.name != _MACRO.name and _SHELL_CLASS in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_roster_save_bar_keeps_apply_and_reset_buttons() -> None:
    app, _deps = _build_app()
    client = TestClient(app)
    client.post("/admin/auth/telegram", data=_signed_widget_fields())
    html = client.get("/admin/roster").text

    assert 'id="roster-apply"' in html
    assert 'id="roster-reset"' in html
    assert "Применить" in html
    assert "Сбросить" in html


def test_save_bar_macro_hidden_keeps_class_and_attribute() -> None:
    template = TEMPLATES.env.from_string(
        '{% from "_admin_save_bar.html" import admin_save_bar %}'
        "{% call admin_save_bar(hidden=true) %}<button>Сохранить</button>{% endcall %}"
    )
    html = template.render()

    assert _SHELL_CLASS in html
    assert " hidden" in html
    assert ">Сохранить<" in html


def test_manual_save_bar_copy_is_rejected_by_guard() -> None:
    copied = '<div class="admin-save-bar"><button>Сохранить</button></div>'
    inline_script = 'document.querySelector(".admin-save-bar")'

    assert _SHELL_CLASS in copied
    assert _SHELL_CLASS not in inline_script
