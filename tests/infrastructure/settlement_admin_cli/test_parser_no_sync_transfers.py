from __future__ import annotations

import pytest
from scripts.settlement_admin_lib.parser import build_parser


def test_parser_has_no_sync_transfers_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "sync-transfers",
                "--technician-id",
                "1",
                "--anchor-at",
                "2026-06-15T00:00:00+00:00",
            ],
        )
