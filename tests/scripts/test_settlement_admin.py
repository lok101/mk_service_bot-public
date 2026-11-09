from __future__ import annotations

import pytest
from scripts.settlement_admin import build_parser


def test_parser_supports_reconcile_preview() -> None:
    args = build_parser().parse_args(
        [
            "reconcile",
            "preview",
            "--technician-id",
            "tech-a",
        ],
    )
    assert args.command == "reconcile"
    assert args.reconcile_command == "preview"
    assert args.technician_id == "tech-a"


def test_parser_supports_reconcile_preview_without_technician_id() -> None:
    args = build_parser().parse_args(
        [
            "reconcile",
            "preview",
        ],
    )
    assert args.command == "reconcile"
    assert args.reconcile_command == "preview"
    assert args.technician_id is None


def test_reconcile_preview_parser_has_no_anchor_at() -> None:
    """error: --anchor-at на reconcile preview → SystemExit (unknown arg)."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "reconcile",
                "preview",
                "--technician-id",
                "tech-a",
                "--anchor-at",
                "2026-05-25T00:00:00+00:00",
            ],
        )


def test_import_transfers_parser_has_no_anchor_at() -> None:
    """error: --anchor-at на import-transfers → SystemExit."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "import-transfers",
                "--technician-id",
                "10001",
                "--anchor-at",
                "2026-07-01T00:00:00+00:00",
            ],
        )


def test_run_command_removed() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run"])


def test_parser_supports_list_blockers() -> None:
    args = build_parser().parse_args(["list-blockers", "--technician-id", "10003"])
    assert args.command == "list-blockers"
    assert args.technician_id == "10003"


def test_parser_supports_close_technician_warehouse() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["close-technician-warehouse", "--technician-id", "tech-1", "--confirm"],
    )
    assert args.command == "close-technician-warehouse"
    assert args.technician_id == "tech-1"
    assert args.confirm is True


def test_close_parser_defaults_confirm_false() -> None:
    args = build_parser().parse_args(
        ["close-technician-warehouse", "--technician-id", "tech-1"],
    )
    assert args.confirm is False


def test_exit_reconcile_preview_allows_omit_technician_id() -> None:
    args = build_parser().parse_args(["exit-reconcile", "preview"])
    assert args.command == "exit-reconcile"
    assert args.exit_reconcile_command == "preview"
    assert args.technician_id is None
    assert args.all is False


def test_exit_reconcile_preview_parses_technician_id() -> None:
    args = build_parser().parse_args(
        ["exit-reconcile", "preview", "--technician-id", "tech-1"],
    )
    assert args.command == "exit-reconcile"
    assert args.exit_reconcile_command == "preview"
    assert args.technician_id == "tech-1"


def test_exit_reconcile_finalize_requires_confirm_flag_present() -> None:
    args = build_parser().parse_args(
        [
            "exit-reconcile",
            "finalize",
            "--technician-id",
            "tech-1",
            "--confirm",
        ],
    )
    assert args.exit_reconcile_command == "finalize"
    assert args.confirm is True


def test_exit_reconcile_parser_has_no_anchor_at() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "exit-reconcile",
                "preview",
                "--technician-id",
                "tech-1",
                "--anchor-at",
                "2026-07-01T00:00:00+00:00",
            ],
        )


def test_parser_rejects_legacy_termination_cli_flag() -> None:
    parser = build_parser()
    legacy_flag = "--" + "termination" + "-finalize"
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "reconcile",
                "finalize",
                "--technician-id",
                "tech-1",
                "--confirm",
                legacy_flag,
            ],
        )
