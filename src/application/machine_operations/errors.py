from __future__ import annotations

MACHINE_OPERATIONS_CONCURRENCY_REASON = (
    "Не удалось сохранить операцию из-за параллельного изменения. Повторите отправку."
)


class MachineOperationsConcurrencyError(Exception):
    """Raised when optimistic persistence loses a race after all retries."""
