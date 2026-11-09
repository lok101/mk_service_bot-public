from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats
from src.infrastructure.matrix_automation.telegram_notifier import MatrixJobTelegramNotifier

from .fakes import _DELTA, _job, _unit


def test_notify_posts_messages_in_main_blocked_kept_order(monkeypatch) -> None:
    import json

    from src.application.matrix_automation.models import BlockedProductRef

    posted: list[str] = []

    class _Response:
        status = 200

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        payload = json.loads(request.data.decode("utf-8"))
        posted.append(payload["text"])
        assert payload["chat_id"] == -100
        assert "sendMessage" in request.full_url
        return _Response()

    monkeypatch.setattr(
        "src.infrastructure.matrix_automation.telegram_notifier.urllib.request.urlopen",
        fake_urlopen,
    )
    job = _job(
        status="completed",
        units=(
            _unit(
                sku_stats=SkuStats(applied=5, kept_previous=3, skipped_no_baseline=0),
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="unknown_product_name",
                detail="x",
                products=(BlockedProductRef(product_name="Cola", product_code=None),),
                machine_codes=("512",),
            ),
        ),
    )
    notifier = MatrixJobTelegramNotifier(
        bot_token="token",
        chat_id=-100,
        max_price_delta_pct=_DELTA,
        kept_alert_pct=Decimal("20"),
    )

    notifier.notify(job)

    assert len(posted) == 3
    assert posted[0].startswith("Matrix deploy job completed")
    assert posted[1].startswith("Matrix deploy: blocked matrices")
    assert posted[2].startswith("⚠️ Matrix deploy: high kept_previous")


def test_transport_failure_logs_full_summary_and_does_not_raise(monkeypatch, caplog) -> None:
    import logging
    import urllib.error

    def boom(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(
        "src.infrastructure.matrix_automation.telegram_notifier.urllib.request.urlopen",
        boom,
    )
    job = _job(
        status="completed",
        units=(_unit(sku_stats=SkuStats(applied=1)),),
    )
    notifier = MatrixJobTelegramNotifier(
        bot_token="token",
        chat_id=-100,
        max_price_delta_pct=_DELTA,
        kept_alert_pct=Decimal("20"),
    )

    with caplog.at_level(logging.ERROR):
        notifier.notify(job)

    assert any("matrix_job_telegram_notify_failed" in record.message for record in caplog.records)
    assert any(
        job.job_id in str(getattr(record, "job_id", "")) or job.job_id in record.getMessage()
        for record in caplog.records
    ) or any("job-1" in str(record.__dict__) for record in caplog.records)


def test_transport_failure_puts_job_id_status_and_messages_in_log_message(
    monkeypatch,
    caplog,
) -> None:
    import logging
    import urllib.error

    def boom(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(
        "src.infrastructure.matrix_automation.telegram_notifier.urllib.request.urlopen",
        boom,
    )
    job = _job(
        status="completed",
        units=(_unit(sku_stats=SkuStats(applied=1)),),
    )
    notifier = MatrixJobTelegramNotifier(
        bot_token="token",
        chat_id=-100,
        max_price_delta_pct=_DELTA,
        kept_alert_pct=Decimal("20"),
    )

    with caplog.at_level(logging.ERROR):
        notifier.notify(job)

    messages = [record.getMessage() for record in caplog.records]
    assert any("job-1" in message for message in messages)
    assert any("completed" in message for message in messages)
    assert any("Matrix deploy job completed" in message for message in messages)


def test_notify_continues_after_first_message_transport_failure(monkeypatch, caplog) -> None:
    import json
    import logging
    import urllib.error

    from src.application.matrix_automation.models import BlockedProductRef

    posted: list[str] = []
    calls = {"n": 0}

    class _Response:
        status = 200

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def flaky_urlopen(request, timeout=None):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("network down")
        payload = json.loads(request.data.decode("utf-8"))
        posted.append(payload["text"])
        return _Response()

    monkeypatch.setattr(
        "src.infrastructure.matrix_automation.telegram_notifier.urllib.request.urlopen",
        flaky_urlopen,
    )
    job = _job(
        status="completed",
        units=(
            _unit(
                sku_stats=SkuStats(applied=5, kept_previous=3, skipped_no_baseline=0),
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="unknown_product_name",
                detail="x",
                products=(BlockedProductRef(product_name="Cola", product_code=None),),
                machine_codes=("512",),
            ),
        ),
    )
    notifier = MatrixJobTelegramNotifier(
        bot_token="token",
        chat_id=-100,
        max_price_delta_pct=_DELTA,
        kept_alert_pct=Decimal("20"),
    )

    with caplog.at_level(logging.ERROR):
        notifier.notify(job)

    assert len(posted) == 2
    assert posted[0].startswith("Matrix deploy: blocked matrices")
    assert posted[1].startswith("⚠️ Matrix deploy: high kept_previous")
    assert any("matrix_job_telegram_notify_failed" in record.message for record in caplog.records)
