from __future__ import annotations


class EventStoreConcurrencyError(Exception):
    """Raised when optimistic append loses a race on aggregate_version."""
