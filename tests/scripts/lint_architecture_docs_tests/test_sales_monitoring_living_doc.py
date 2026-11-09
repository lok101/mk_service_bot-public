from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LIVING = _ROOT / "docs" / "sales-monitoring.md"
_SYSTEM_MAP = _ROOT / "docs" / "README.md"
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")
_DOMAIN_UMBRELLA = "2026-07-28-sales-monitoring-domain-design.md"

_REQUIRED = (
    "## Действует сейчас",
    "## Утверждено, но не внедрено",
    "## Ключевые решения",
    "## Основные пути кода",
    "## Полная документация",
)


def test_sales_monitoring_living_doc_has_required_sections() -> None:
    text = _LIVING.read_text(encoding="utf-8")
    assert text.lstrip().startswith("#")
    for heading in _REQUIRED:
        assert heading in text, heading
    assert "ADR-0012" in text
    assert "ADR-0015" in text


def test_sales_monitoring_living_doc_keeps_target_out_of_current() -> None:
    text = _LIVING.read_text(encoding="utf-8")
    assert "## Утверждено, но не внедрено" in text
    after = text.split("## Действует сейчас", 1)[1]
    current, _sep, _rest = after.partition("## Утверждено, но не внедрено")
    assert "## Утверждено, но не внедрено" not in current


def test_system_map_sales_monitoring_primary_is_living_doc() -> None:
    text = _SYSTEM_MAP.read_text(encoding="utf-8")
    table = text.split("## System map", 1)[1].split("\n## ", 1)[0]
    rows = [ln for ln in table.splitlines() if ln.startswith("| Sales monitoring")]
    assert len(rows) == 1, rows
    cells = [c.strip() for c in rows[0].strip("|").split("|")]
    primary, coverage = cells[2], cells[5]
    md_targets = _MD_LINK.findall(primary)
    assert len(md_targets) == 1, primary
    assert md_targets[0].endswith("sales-monitoring.md"), md_targets
    assert coverage == "living", coverage
    assert _DOMAIN_UMBRELLA not in primary
