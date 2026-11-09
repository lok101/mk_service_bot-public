from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation import (
    BlockedMatrixEntry,
    MatrixDeployJob,
    MatrixDeployJobUnit,
    MatrixJobNotifier,
    ProductSwapBlockedLine,
    SkuStats,
    StrongPriceIncreaseLine,
    human_description_for,
)

_logger = logging.getLogger(__name__)

_MAX_LIST_ITEMS = 10
_TELEGRAM_API_TIMEOUT_SECONDS = 10.0


@beartype
def _unit_counts(job: MatrixDeployJob) -> tuple[int, int, int]:
    applied = sum(1 for unit in job.units if unit.deploy_status == "applied")
    failed = sum(1 for unit in job.units if unit.deploy_status == "failed")
    skipped = sum(1 for unit in job.units if unit.deploy_status == "skipped")
    return applied, failed, skipped


@beartype
def _sum_sku_stats(job: MatrixDeployJob) -> SkuStats:
    applied = 0
    kept_previous = 0
    skipped_no_baseline = 0
    strong_price_increase = 0
    blocked_empty = 0
    product_swap_blocked = 0
    for unit in job.units:
        stats = unit.sku_stats
        if stats is None:
            continue
        applied += stats.applied
        kept_previous += stats.kept_previous
        skipped_no_baseline += stats.skipped_no_baseline
        strong_price_increase += stats.strong_price_increase
        blocked_empty += stats.blocked_empty
        product_swap_blocked += stats.product_swap_blocked
    return SkuStats(
        applied=applied,
        kept_previous=kept_previous,
        skipped_no_baseline=skipped_no_baseline,
        strong_price_increase=strong_price_increase,
        blocked_empty=blocked_empty,
        product_swap_blocked=product_swap_blocked,
    )


@beartype
def _sku_line(stats: SkuStats) -> str:
    segments = [
        f"applied {stats.applied}",
        f"kept_previous {stats.kept_previous}",
        f"skipped_no_baseline {stats.skipped_no_baseline}",
    ]
    if stats.blocked_empty > 0:
        segments.append(f"blocked_empty {stats.blocked_empty}")
    if stats.product_swap_blocked > 0:
        segments.append(f"product_swap_blocked {stats.product_swap_blocked}")
    return "SKU: " + " | ".join(segments)


@beartype
def _tail(remaining: int, noun: str) -> str:
    return f"  • … и ещё {remaining} {noun}"


@beartype
def _sorted_strong_lines(
    job: MatrixDeployJob,
) -> list[StrongPriceIncreaseLine]:
    lines = [line for unit in job.units for line in unit.strong_price_increase_lines]
    return sorted(
        lines,
        key=lambda line: (-Decimal(line.increase_pct), line.machine_code, line.line_number),
    )


@beartype
def _sorted_swap_lines(job: MatrixDeployJob) -> list[ProductSwapBlockedLine]:
    lines = [line for unit in job.units for line in unit.product_swap_blocked_lines]
    return sorted(lines, key=lambda line: (line.machine_code, line.line_number))


@beartype
def _failed_units(job: MatrixDeployJob) -> list[MatrixDeployJobUnit]:
    failed = [unit for unit in job.units if unit.deploy_status == "failed"]
    return sorted(failed, key=lambda unit: (unit.logical_matrix_name, unit.machine_code))


@beartype
def _format_strong_block(
    job: MatrixDeployJob,
    *,
    max_price_delta_pct: Decimal,
    count: int,
) -> list[str]:
    if count == 0:
        return []
    lines = _sorted_strong_lines(job)
    block = [f"Товары с сильным повышением цены (> {max_price_delta_pct}%): {count}"]
    for line in lines[:_MAX_LIST_ITEMS]:
        product = line.product_code or "(empty)"
        block.append(
            f"  • {line.machine_code} L{line.line_number} {product}: "
            f"{line.baseline} → {line.deploy_price} (+{line.increase_pct}%)"
        )
    remaining = len(lines) - _MAX_LIST_ITEMS
    if remaining > 0:
        block.append(_tail(remaining, "товар(ов)"))
    return block


@beartype
def _format_swap_block(job: MatrixDeployJob, *, count: int) -> list[str]:
    if count == 0:
        return []
    lines = _sorted_swap_lines(job)
    block = [f"Смена товара заблокирована (остаток): {count}"]
    for line in lines[:_MAX_LIST_ITEMS]:
        current = line.current_product or "(empty)"
        desired = "(empty)" if line.desired_product is None else line.desired_product
        reason = line.reason or ""
        block.append(
            f"  • {line.machine_code} L{line.line_number} {current} → {desired} ({reason})"
        )
    remaining = len(lines) - _MAX_LIST_ITEMS
    if remaining > 0:
        block.append(_tail(remaining, "ячеек"))
    return block


@beartype
def _format_deploy_failed_block(job: MatrixDeployJob, *, failed_count: int) -> list[str]:
    if failed_count == 0:
        return []
    units = _failed_units(job)
    block = ["Deploy failed:"]
    for unit in units[:_MAX_LIST_ITEMS]:
        block.append(f"  • {unit.logical_matrix_name} / {unit.machine_code}: {unit.deploy_reason}")
    remaining = len(units) - _MAX_LIST_ITEMS
    if remaining > 0:
        block.append(_tail(remaining, "аппарат(ов)"))
    return block


@beartype
def _job_title(job: MatrixDeployJob, *, status_word: str) -> str:
    if job.trigger == "seed":
        return f"Matrix deploy job (seed) {status_word}"
    return f"Matrix deploy job {status_word}"


@beartype
def format_main_summary(
    job: MatrixDeployJob,
    *,
    global_abort_reason: str | None,
    max_price_delta_pct: Decimal = Decimal("30"),
) -> str:
    if global_abort_reason is not None:
        return f"{_job_title(job, status_word='failed')}\nReason: {global_abort_reason}"

    applied, failed, skipped = _unit_counts(job)
    blocked_count = len(job.blocked_matrices)
    disabled = job.auto_sync_disabled_matrices

    if job.status == "skipped":
        lines = [
            _job_title(job, status_word="skipped"),
            f"Matrices auto-sync disabled: {disabled}",
        ]
        if skipped == 0:
            lines.append("Units: 0/0/0")
            lines.append("нет enabled-матриц для deploy")
        else:
            lines.append(f"Units: 0/0/{skipped}")
            lines.append(f"Blocked matrices: {blocked_count}")
            lines.append("Kit deploy не выполнялся")
        return "\n".join(lines)

    stats = _sum_sku_stats(job)
    lines = [
        _job_title(job, status_word=str(job.status)),
        f"Units: applied {applied} / failed {failed} / skipped {skipped}",
        f"Matrices auto-sync disabled: {disabled}",
        f"Blocked matrices: {blocked_count}",
        _sku_line(stats),
    ]
    lines.extend(
        _format_strong_block(
            job,
            max_price_delta_pct=max_price_delta_pct,
            count=stats.strong_price_increase,
        )
    )
    lines.extend(_format_swap_block(job, count=stats.product_swap_blocked))
    lines.extend(_format_deploy_failed_block(job, failed_count=failed))
    return "\n".join(lines)


@beartype
def format_blocked_matrices_message(job: MatrixDeployJob) -> str | None:
    if not job.blocked_matrices:
        return None
    entries = list(job.blocked_matrices)
    lines = [f"Matrix deploy: blocked matrices ({len(entries)})", ""]
    for entry in entries[:_MAX_LIST_ITEMS]:
        lines.extend(_format_blocked_entry(entry))
    remaining = len(entries) - _MAX_LIST_ITEMS
    if remaining > 0:
        lines.append(_tail(remaining, "матриц(ы)").lstrip())
    return "\n".join(lines).rstrip()


@beartype
def _format_blocked_entry(entry: BlockedMatrixEntry) -> list[str]:
    lines = [
        f"• {entry.logical_matrix_name}",
        f"  Reason: {entry.deploy_reason}",
        f"  {human_description_for(deploy_reason=entry.deploy_reason, detail=entry.detail)}",
    ]
    if entry.products:
        products: list[str] = []
        for product in entry.products:
            if entry.deploy_reason == "unknown_product_name" or product.product_code is None:
                code = "unknown"
            else:
                code = product.product_code
            products.append(f"{product.product_name} ({code})")
        lines.append(f"  Products: {', '.join(products)}")
    lines.append("")
    return lines


@beartype
def kept_alert_text(job: MatrixDeployJob, threshold: Decimal) -> str | None:
    stats = _sum_sku_stats(job)
    total_sku = stats.applied + stats.kept_previous + stats.skipped_no_baseline
    if total_sku == 0:
        return None
    pct = (Decimal(stats.kept_previous) / Decimal(total_sku)) * Decimal("100")
    if pct <= threshold:
        return None
    rounded = round(float(pct), 1)
    return "\n".join(
        [
            f"⚠️ Matrix deploy: high kept_previous (Bk/total_sku = {rounded}%)",
            f"Threshold: {threshold}%",
            f"SKU kept_previous: {stats.kept_previous} / total_sku: {total_sku}",
        ]
    )


@beartype
def build_notify_messages(
    job: MatrixDeployJob,
    *,
    global_abort_reason: str | None,
    max_price_delta_pct: Decimal,
    kept_alert_pct: Decimal,
) -> list[str]:
    messages = [
        format_main_summary(
            job,
            global_abort_reason=global_abort_reason,
            max_price_delta_pct=max_price_delta_pct,
        )
    ]
    if global_abort_reason is None and job.blocked_matrices:
        blocked = format_blocked_matrices_message(job)
        if blocked is not None:
            messages.append(blocked)
    if global_abort_reason is None:
        kept = kept_alert_text(job, kept_alert_pct)
        if kept is not None:
            messages.append(kept)
    return messages


@beartype
@dataclass(slots=True)
class MatrixJobTelegramNotifier(MatrixJobNotifier):
    bot_token: str
    chat_id: int
    max_price_delta_pct: Decimal
    kept_alert_pct: Decimal
    _send: Callable[[str], None] | None = None

    @beartype
    def notify(
        self,
        job: MatrixDeployJob,
        *,
        global_abort_reason: str | None = None,
    ) -> None:
        messages = build_notify_messages(
            job,
            global_abort_reason=global_abort_reason,
            max_price_delta_pct=self.max_price_delta_pct,
            kept_alert_pct=self.kept_alert_pct,
        )
        for text in messages:
            try:
                self._post_message(text)
            except urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError:
                _logger.error(
                    "matrix_job_telegram_notify_failed job_id=%s status=%s\n%s",
                    job.job_id,
                    job.status,
                    text,
                    extra={
                        "job_id": job.job_id,
                        "status": job.status,
                        "messages": messages,
                    },
                )

    @beartype
    def _post_message(self, text: str) -> None:
        if self._send is not None:
            self._send(text)
            return
        payload = json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TELEGRAM_API_TIMEOUT_SECONDS) as response:
            if response.status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    response.status,
                    response.reason or "",
                    response.headers,
                    None,
                )
