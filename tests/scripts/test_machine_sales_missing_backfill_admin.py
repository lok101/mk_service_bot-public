from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.inventory_reconciliation import BackfillMissingSalesFromKitResult
from src.infrastructure.integrations.kitvending.http_client import KitVendingNetworkError


def test_build_deps_passes_company_store_to_build_kitvending_client() -> None:
    from scripts import machine_sales_missing_backfill_admin as mod

    source = inspect.getsource(mod._build_deps)
    assert "build_company_store" in source
    assert "company_store=company_store" in source


def test_build_deps_passes_domain_product_store_to_refresh() -> None:
    # error: refresh сверки требует склад доменных товаров, иначе CLI падает до Kit
    from scripts import machine_sales_missing_backfill_admin as mod

    source = inspect.getsource(mod._build_deps)
    assert "build_domain_product_store" in source
    assert "domain_product_store=domain_product_store" in source


def test_build_deps_exits_without_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    # error: нет Mongo
    from src.config.mongodb import MongoSettings

    @dataclass(frozen=True, slots=True)
    class _FakeSettings:
        mongodb: MongoSettings

    monkeypatch.setattr(
        "scripts.machine_sales_missing_backfill_admin.get_settings",
        lambda: _FakeSettings(mongodb=MongoSettings()),
    )
    from scripts.machine_sales_missing_backfill_admin import _build_deps

    with pytest.raises(SystemExit) as exc_info:
        _build_deps()
    assert exc_info.value.code == 1


@dataclass(frozen=True, slots=True)
class _FakeUseCase:
    result: BackfillMissingSalesFromKitResult | None = None
    error: Exception | None = None
    captured_refresh: list[bool] = field(default_factory=list)

    def execute(
        self,
        *,
        since: datetime,
        until: datetime,
        refresh_settlement: bool = False,
    ) -> BackfillMissingSalesFromKitResult:
        del since, until
        self.captured_refresh.append(refresh_settlement)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_run_prints_summary_and_returns_zero_on_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # happy: counters напечатаны, exit 0
    result = BackfillMissingSalesFromKitResult(
        window_from=datetime(2026, 8, 10, tzinfo=UTC),
        window_to=datetime(2026, 8, 11, tzinfo=UTC),
        inserted=3,
        skipped_unmapped=1,
        refreshed_machine_count=2,
    )
    from scripts.machine_sales_missing_backfill_admin import run

    code = run(
        use_case=_FakeUseCase(result=result),
        since=result.window_from,
        until=result.window_to,
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "inserted=3" in out
    assert "skipped_unmapped=1" in out
    assert "refreshed_machine_count=2" in out


def test_run_returns_non_zero_when_kit_fetch_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # error: Kit HTTP failure → abort, non-zero
    from scripts.machine_sales_missing_backfill_admin import run

    since = datetime(2026, 8, 10, tzinfo=UTC)
    until = datetime(2026, 8, 11, tzinfo=UTC)
    code = run(
        use_case=_FakeUseCase(error=KitVendingNetworkError("boom")),
        since=since,
        until=until,
    )
    err = capsys.readouterr().err

    assert code == 1
    assert "Kit API failure" in err


def test_parser_refresh_settlement_default_false() -> None:
    from scripts.machine_sales_missing_backfill_admin import build_parser

    args = build_parser().parse_args(["--since", "2026-08-10T00:00:00+00:00"])
    assert args.refresh_settlement is False


def test_parser_refresh_settlement_flag_true() -> None:
    from scripts.machine_sales_missing_backfill_admin import build_parser

    args = build_parser().parse_args(
        ["--since", "2026-08-10T00:00:00+00:00", "--refresh-settlement"],
    )
    assert args.refresh_settlement is True


def test_run_forwards_refresh_settlement_false() -> None:
    result = BackfillMissingSalesFromKitResult(
        window_from=datetime(2026, 8, 10, tzinfo=UTC),
        window_to=datetime(2026, 8, 11, tzinfo=UTC),
        inserted=1,
    )
    fake = _FakeUseCase(result=result)
    from scripts.machine_sales_missing_backfill_admin import run

    code = run(
        use_case=fake,
        since=result.window_from,
        until=result.window_to,
        refresh_settlement=False,
    )
    assert code == 0
    assert fake.captured_refresh == [False]


def test_run_forwards_refresh_settlement_true() -> None:
    result = BackfillMissingSalesFromKitResult(
        window_from=datetime(2026, 8, 10, tzinfo=UTC),
        window_to=datetime(2026, 8, 11, tzinfo=UTC),
        inserted=1,
        refreshed_machine_count=1,
    )
    fake = _FakeUseCase(result=result)
    from scripts.machine_sales_missing_backfill_admin import run

    code = run(
        use_case=fake,
        since=result.window_from,
        until=result.window_to,
        refresh_settlement=True,
    )
    assert code == 0
    assert fake.captured_refresh == [True]


def test_main_requires_since() -> None:
    # error: --since обязателен (argparse завершает процесс с кодом 2)
    from scripts.machine_sales_missing_backfill_admin import main

    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2


def test_main_rejects_invalid_since_format(capsys: pytest.CaptureFixture[str]) -> None:
    # error: невалидный формат даты
    from scripts.machine_sales_missing_backfill_admin import main

    code = main(["--since", "not-a-date"])
    err = capsys.readouterr().err

    assert code == 2
    assert "invalid --since datetime" in err


def test_main_rejects_since_after_to(capsys: pytest.CaptureFixture[str]) -> None:
    # error: --since > --to — validation error до Kit
    from scripts.machine_sales_missing_backfill_admin import main

    code = main(
        [
            "--since",
            "2026-08-11T00:00:00+00:00",
            "--to",
            "2026-08-10T00:00:00+00:00",
        ],
    )
    err = capsys.readouterr().err

    assert code == 2
    assert "--since must be <= --to" in err
