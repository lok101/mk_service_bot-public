from __future__ import annotations

from pathlib import Path

from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.promote import promote_report
from scripts.agent_process_report_lib.store import create_report, load_report


def test_promote_creates_apb_record(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    problems = tmp_path / "problems"
    problems.mkdir()
    (problems / "README.md").write_text(
        "# Index\n\n| APB id | Status | Signatures | Linear |\n"
        "|--------|--------|------------|--------|\n"
        "| _(empty until first promote)_ | | | |\n",
        encoding="utf-8",
    )
    report = create_report(
        common,
        new_report(
            kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
            outcome=ReportOutcome.BLOCKED,
            surface="aec.hook",
            operation="shell",
            signature="agt007-residue",
            expected="deny",
            actual="blocked",
            evidence={},
            report_id="apr-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        ),
    )
    stem, path = promote_report(
        common,
        report.report_id,
        slug="agt007-residue",
        problems_dir=problems,
    )
    assert stem == "APB-0001-agt007-residue"
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "apr-eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee" in body
    assert "open" in body
    index = (problems / "README.md").read_text(encoding="utf-8")
    assert "APB-0001-agt007-residue" in index
    updated = load_report(common, report.report_id)
    assert updated.promotion is not None
    assert updated.promotion.get("status") == "promoted"
