from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from beartype import beartype


@runtime_checkable
class WebhookRateLimiter(Protocol):
    @beartype
    def check(self, client_ip: str) -> bool: ...

    @property
    def retry_after_seconds(self) -> int: ...


@dataclass
class InMemoryWebhookRateLimiter:
    max_requests: int
    window_seconds: float
    max_tracked_ips: int = 10_000
    _buckets: OrderedDict[str, list[float]] = field(default_factory=OrderedDict)

    @property
    def retry_after_seconds(self) -> int:
        return max(1, int(self.window_seconds))

    @beartype
    def _prune_expired_ips(self, now: float) -> None:
        if len(self._buckets) <= self.max_tracked_ips // 2:
            return
        window_start = now - self.window_seconds
        expired = [
            ip
            for ip, hits in self._buckets.items()
            if not any(timestamp >= window_start for timestamp in hits)
        ]
        for ip in expired:
            del self._buckets[ip]

    @beartype
    def check(self, client_ip: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        self._prune_expired_ips(now)

        hits = [
            timestamp for timestamp in self._buckets.get(client_ip, []) if timestamp >= window_start
        ]

        if len(hits) >= self.max_requests:
            if hits:
                self._buckets[client_ip] = hits
                self._buckets.move_to_end(client_ip)
            elif client_ip in self._buckets:
                del self._buckets[client_ip]
            return False

        hits.append(now)
        self._buckets[client_ip] = hits
        self._buckets.move_to_end(client_ip)

        while len(self._buckets) > self.max_tracked_ips:
            self._buckets.popitem(last=False)

        return True
