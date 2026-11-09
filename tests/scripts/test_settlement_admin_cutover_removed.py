from __future__ import annotations

import pytest
from scripts.settlement_admin_lib.parser import build_parser

_CUTOVER_ARGV: tuple[tuple[str, ...], ...] = (
    ("wipe", "--dry-run"),
    ("rebuild-periods", "--all"),
    ("recalculate-periods", "--all"),
    ("post-ledger", "--all"),
    (
        "seed-warehouse-baseline",
        "--write-template",
        "--technician-id",
        "t1",
        "--output",
        "o.json",
    ),
    ("backfill-warehouse-loadings", "--technician-id", "t1"),
    ("wipe-technician-warehouse", "--technician-id", "t1", "--dry-run"),
)


@pytest.mark.parametrize("argv", _CUTOVER_ARGV)
def test_parser_rejects_cutover_commands(argv: tuple[str, ...]) -> None:
    """error: cutover subcommands removed after cutover done."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(list(argv))


def test_parser_keeps_product_commands() -> None:
    """happy: product surface still parses."""
    parser = build_parser()
    assert (
        parser.parse_args(
            ["list-blockers", "--technician-id", "10003"],
        ).command
        == "list-blockers"
    )
    assert parser.parse_args(["list-status"]).command == "list-status"
    assert (
        parser.parse_args(
            [
                "reconcile",
                "preview",
                "--technician-id",
                "tech-1",
            ],
        ).reconcile_command
        == "preview"
    )
    assert (
        parser.parse_args(
            ["reconcile", "finalize", "--technician-id", "tech-1", "--confirm"],
        ).reconcile_command
        == "finalize"
    )
    assert (
        parser.parse_args(
            [
                "import-transfers",
                "--technician-id",
                "tech-1",
            ],
        ).command
        == "import-transfers"
    )
    assert (
        parser.parse_args(
            ["close-technician-warehouse", "--technician-id", "tech-1", "--confirm"],
        ).command
        == "close-technician-warehouse"
    )
    assert (
        parser.parse_args(
            ["exit-reconcile", "preview", "--technician-id", "tech-1"],
        ).exit_reconcile_command
        == "preview"
    )
    assert (
        parser.parse_args(
            ["exit-reconcile", "finalize", "--technician-id", "tech-1", "--confirm"],
        ).exit_reconcile_command
        == "finalize"
    )
