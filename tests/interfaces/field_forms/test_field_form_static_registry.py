from __future__ import annotations

from pathlib import Path

from src.interfaces.field_forms.http_common import TEMPLATES, static_href, static_version

_FIELD_FORMS_ROOT = Path("src/interfaces/field_forms")
_TEMPLATES_ROOT = _FIELD_FORMS_ROOT / "templates"
_OWNER_MODULES = {
    "src/interfaces/field_forms/http_common.py",
}


def test_static_href_uses_mtime_of_existing_file() -> None:
    name = "field_form.css"
    href = static_href(name)
    path = _FIELD_FORMS_ROOT / "static" / name
    version = str(int(path.stat().st_mtime))

    assert href == f"/forms/static/{name}?v={version}"
    assert static_version(name) == version
    assert TEMPLATES.env.globals["static_href"] is static_href


def test_static_href_missing_file_uses_version_zero() -> None:
    assert static_href("missing-field-asset.js") == "/forms/static/missing-field-asset.js?v=0"


def test_jinja_templates_constructor_lives_in_one_owner_module() -> None:
    hits = [
        path.as_posix()
        for path in _FIELD_FORMS_ROOT.rglob("*.py")
        if "Jinja2Templates(" in path.read_text(encoding="utf-8")
    ]

    assert len(hits) == 1
    assert hits[0] in _OWNER_MODULES


def test_production_templates_have_no_bare_static_url() -> None:
    offenders = [
        path.as_posix()
        for path in _TEMPLATES_ROOT.rglob("*.html")
        if "/forms/static/" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
