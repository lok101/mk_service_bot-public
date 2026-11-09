from __future__ import annotations

import inspect

import scripts.settlement_admin as shim
from scripts.settlement_admin_lib import main as lib_main
from scripts.settlement_admin_lib.deps import CliDeps, build_deps


def test_settlement_admin_shim_exports_only_main_and_build_parser() -> None:
    assert callable(shim.main)
    assert callable(shim.build_parser)
    assert shim.main is lib_main.main
    assert not hasattr(shim, "build_deps")
    assert not hasattr(shim, "CliDeps")
    assert callable(build_deps)
    assert inspect.isclass(CliDeps)
    # shim — тонкий файл, не монолит
    assert len(inspect.getsource(shim)) < 800


def test_cli_monkeypatch_targets_lib_main_build_deps(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_build_deps():
        calls.append("hit")
        raise AssertionError("stop-after-build_deps")

    monkeypatch.setattr(lib_main, "build_deps", _fake_build_deps)
    try:
        shim.main(["list-blockers", "--technician-id", "10003"])
    except AssertionError as exc:
        assert str(exc) == "stop-after-build_deps"
    assert calls == ["hit"]
