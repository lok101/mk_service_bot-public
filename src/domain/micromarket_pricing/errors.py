from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class MultiplierOutOfBounds:
    value: str
    min_bound: str
    max_bound: str
