from __future__ import annotations

from beartype import beartype


@beartype
class SecondCommandRejected(Exception):
    """Raised when a second loading command is not allowed for this cycle."""
