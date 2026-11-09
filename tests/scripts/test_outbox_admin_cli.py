from __future__ import annotations

import argparse
from dataclasses import dataclass

import pytest
from scripts.outbox_admin import _build_deps, _CliDeps, build_parser, main

from src.application.outbox.admin import (
    GetFailedOutboxEntryService,
    ListFailedOutboxEntriesService,
    RequeueFailedOutboxEntryService,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.outbox.memory import InMemoryOutboxStore


@dataclass(frozen=True, slots=True)
class _FakeSettings:
    mongodb: MongoSettings


def _fake_deps() -> _CliDeps:
    store = InMemoryOutboxStore()
    return _CliDeps(
        list_failed=ListFailedOutboxEntriesService(store=store),
        get_failed=GetFailedOutboxEntryService(store=store),
        requeue_failed=RequeueFailedOutboxEntryService(store=store),
    )


def test_build_parser_parses_list_show_requeue_commands() -> None:
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)

    list_args = parser.parse_args(["list", "--handler-id", "revision_inventory", "--limit", "5"])
    assert list_args.command == "list"
    assert list_args.handler_id == "revision_inventory"
    assert list_args.limit == 5

    show_args = parser.parse_args(["show", "entry-abc"])
    assert show_args.command == "show"
    assert show_args.entry_id == "entry-abc"

    requeue_args = parser.parse_args(["requeue", "entry-abc"])
    assert requeue_args.command == "requeue"
    assert requeue_args.entry_id == "entry-abc"


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.outbox_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )

    with pytest.raises(SystemExit, match="MONGODB_URI"):
        _build_deps()


def test_main_returns_error_for_invalid_limit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("scripts.outbox_admin._build_deps", _fake_deps)

    exit_code = main(["list", "--limit", "0"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "limit must be at least 1" in captured.err
