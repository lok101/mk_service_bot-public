from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from src.application.inventory_reconciliation import BackfillSalePricesFromKitResult
from src.infrastructure.integrations.kitvending.http_client import KitVendingNetworkError


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # error: no Mongo
    from src.config.mongodb import MongoSettings

    @dataclass(frozen=True, slots=True)
    class _FakeSettings:
        mongodb: MongoSettings

    monkeypatch.setattr(
        "scripts.machine_sale_price_backfill_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )
    from scripts.machine_sale_price_backfill_admin import _build_deps

    with pytest.raises(SystemExit) as exc_info:
        _build_deps()
    assert exc_info.value.code == 1


@dataclass(frozen=True, slots=True)
class _FakeUseCase:
    result: BackfillSalePricesFromKitResult | None = None
    error: Exception | None = None

    def execute(self) -> BackfillSalePricesFromKitResult:
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_run_prints_summary_and_returns_zero_on_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # happy: counters напечатаны, exit 0
    result = BackfillSalePricesFromKitResult(
        window_from=datetime(2026, 6, 1, tzinfo=UTC),
        window_to=datetime(2026, 7, 29, 8, 19, 54, tzinfo=UTC),
        updated=3,
        already_priced_skipped=1,
        missing_in_kit=2,
        missing_sum=0,
        invalid_sum=0,
    )
    from scripts.machine_sale_price_backfill_admin import run

    code = run(use_case=_FakeUseCase(result=result))
    out = capsys.readouterr().out

    assert code == 0
    assert "updated=3" in out
    assert "already_priced_skipped=1" in out
    assert "missing_in_kit=2" in out


def test_run_prints_nothing_to_do_when_window_from_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # edge: пустое окно
    result = BackfillSalePricesFromKitResult(
        window_from=None,
        window_to=datetime(2026, 7, 29, 8, 19, 54, tzinfo=UTC),
    )
    from scripts.machine_sale_price_backfill_admin import run

    code = run(use_case=_FakeUseCase(result=result))
    out = capsys.readouterr().out

    assert code == 0
    assert "nothing to do" in out


def test_run_returns_non_zero_when_kit_fetch_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # error: Kit HTTP failure → abort, non-zero
    from scripts.machine_sale_price_backfill_admin import run

    code = run(use_case=_FakeUseCase(error=KitVendingNetworkError("boom")))
    err = capsys.readouterr().err

    assert code == 1
    assert "Kit API failure" in err


def test_main_rejects_unexpected_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    # error: скрипт не принимает аргументы
    from scripts.machine_sale_price_backfill_admin import main

    code = main(["--dry-run"])
    err = capsys.readouterr().err

    assert code == 2
    assert "takes no arguments" in err
