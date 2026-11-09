from __future__ import annotations

from pathlib import Path

from src.application.technician_settlement import format_analysis_rubles
from src.interfaces.admin.http_common import TEMPLATES, static_href, static_version

_ADMIN_ROOT = Path("src/interfaces/admin")
_TEMPLATES_ROOT = _ADMIN_ROOT / "templates"
_ROUTES_ROOT = _ADMIN_ROOT / "routes"
_OWNER_MODULES = {
    "src/interfaces/admin/http_common.py",
    "src/interfaces/admin/admin_jinja.py",
}


def test_static_href_uses_mtime_of_existing_file() -> None:
    name = "admin.css"
    href = static_href(name)
    path = _ADMIN_ROOT / "static" / name
    version = str(int(path.stat().st_mtime))

    assert href == f"/admin/static/{name}?v={version}"
    assert static_version(name) == version
    assert TEMPLATES.env.globals["static_href"] is static_href


def test_static_href_missing_file_uses_version_zero() -> None:
    assert static_href("missing-admin-asset.js") == "/admin/static/missing-admin-asset.js?v=0"


def test_jinja_templates_constructor_lives_in_one_owner_module() -> None:
    hits = [
        path.as_posix()
        for path in _ADMIN_ROOT.rglob("*.py")
        if "Jinja2Templates(" in path.read_text(encoding="utf-8")
    ]

    assert len(hits) == 1
    assert hits[0] in _OWNER_MODULES


def test_production_templates_have_no_bare_static_url() -> None:
    offenders = [
        path.as_posix()
        for path in _TEMPLATES_ROOT.rglob("*.html")
        if "/admin/static/" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_admin_css_version_is_not_frozen_at_import() -> None:
    text = (_ADMIN_ROOT / "http_common.py").read_text(encoding="utf-8")
    assert "_ADMIN_CSS_VERSION" not in text


def test_routes_do_not_own_static_version_helpers() -> None:
    offenders = [
        path.as_posix()
        for path in _ROUTES_ROOT.rglob("*.py")
        if _owns_static_helper(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_analysis_rubles_filter_is_on_shared_env() -> None:
    import src.interfaces.admin.routes.settlement_analysis  # noqa: F401

    assert TEMPLATES.env.filters["analysis_rubles"] is format_analysis_rubles


def _owns_static_helper(source: str) -> bool:
    return "_STATIC_DIR" in source or "def _static_version" in source
