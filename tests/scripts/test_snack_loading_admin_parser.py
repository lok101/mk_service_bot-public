from __future__ import annotations

import pytest
from scripts.snack_loading_admin import build_parser


def test_snack_loading_admin_parser_modes() -> None:
    parser = build_parser()
    plan = parser.parse_args(["--batches-file", "b.json", "--plan-only"])
    assert plan.plan_only is True
    assert plan.execute is False
    assert plan.resume_run is None

    execute = parser.parse_args(["--batches-file", "b.json", "--execute"])
    assert execute.execute is True

    resume = parser.parse_args(["--resume-run", "run-1"])
    assert resume.resume_run == "run-1"


def test_snack_loading_admin_parser_requires_mode() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--batches-file", "b.json"])
