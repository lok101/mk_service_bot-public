from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_process_report_lib.home_paths import (
    AprStoreUnavailableError,
    default_process_reports_root,
    default_product_id,
    home_process_reports_root,
    load_platform_home,
)
from scripts.agent_process_report_lib.models import ReportKind, ReportOutcome, new_report
from scripts.agent_process_report_lib.store import create_report, load_report


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )


def test_create_and_load_under_home_var(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")

    reports_root = default_process_reports_root(product)
    assert reports_root == home_process_reports_root(home)

    report = new_report(
        kind=ReportKind.HARD_BOUNDARY_ATTEMPT,
        outcome=ReportOutcome.BLOCKED,
        surface="test",
        operation="op",
        signature="sig",
        expected="deny",
        actual="attempt",
        evidence={},
        product_id=default_product_id(product),
    )
    created = create_report(
        tmp_path / "unused-common",
        report,
        reports_root=reports_root,
        journal_git_common_dir=tmp_path / "unused-common",
    )
    assert created.product_id == "mk_service_bot"
    loaded = load_report(
        tmp_path / "unused-common",
        created.report_id,
        reports_root=reports_root,
    )
    assert loaded.report_id == created.report_id
    assert (reports_root / "reports").is_dir()


def test_missing_kernel_ref_fail_closed(tmp_path: Path) -> None:
    product = tmp_path / "bare"
    product.mkdir()
    with pytest.raises(AprStoreUnavailableError):
        load_platform_home(product)
