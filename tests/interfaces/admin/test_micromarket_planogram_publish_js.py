"""Structural contract: publish IIFE lives in static, not long inline in template."""

from __future__ import annotations

import re
from pathlib import Path

_PUBLISH_JS = Path("src/interfaces/admin/static/micromarket_planogram_publish.js")
_TEMPLATE = Path("src/interfaces/admin/templates/micromarket_planogram.html")
_HTTP_COMMON = Path("src/interfaces/admin/http_common.py")


def test_publish_js_file_exists_with_dual_export() -> None:
    # happy: static publish module + dual-export / window name
    source = _PUBLISH_JS.read_text(encoding="utf-8")
    assert "micromarket-planogram-publish-form" in source
    assert "module.exports" in source
    assert "MicromarketPlanogramPublish" in source


def test_planogram_template_uses_versioned_publish_script_not_inline() -> None:
    # happy: template src href; edge: no long inline publish IIFE
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert "micromarket_planogram_publish_js_href" in html
    assert "micromarket-planogram-publish-form" in html
    assert "function showError" not in html
    assert 'fetch(form.getAttribute("action")' not in html
    assert re.search(r"micromarket_planogram_publish_js_href", html)


def test_http_common_exposes_publish_js_href() -> None:
    # happy: registry href in planogram_static_context
    source = _HTTP_COMMON.read_text(encoding="utf-8")
    assert "micromarket_planogram_publish_js_href" in source
    assert "micromarket_planogram_publish.js" in source
