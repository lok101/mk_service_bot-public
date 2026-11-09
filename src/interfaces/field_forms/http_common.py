from __future__ import annotations

from pathlib import Path
from typing import Any

from beartype import beartype
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_PACKAGE_DIR = Path(__file__).parent
_STATIC_DIR = _PACKAGE_DIR / "static"
_HTML_CACHE_HEADERS = {"Cache-Control": "no-cache"}

TEMPLATES = Jinja2Templates(directory=str(_PACKAGE_DIR / "templates"))


@beartype
def static_version(name: str) -> str:
    path = _STATIC_DIR / name
    return str(int(path.stat().st_mtime)) if path.is_file() else "0"


@beartype
def static_href(name: str) -> str:
    return f"/forms/static/{name}?v={static_version(name)}"


TEMPLATES.env.globals["static_href"] = static_href


@beartype
def form_template_response(
    request: Request,
    name: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        name,
        context,
        status_code=status_code,
        headers=_HTML_CACHE_HEADERS,
    )
