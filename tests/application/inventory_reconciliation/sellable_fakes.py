from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MappingSellableProductCodeCatalog:
    """Test / wiring fake: explicit ready flag + code set (already stripped keys)."""

    codes: frozenset[str] = field(default_factory=frozenset)
    _ready: bool = True

    def ready(self) -> bool:
        return self._ready

    def contains(self, code: str) -> bool:
        return code.strip() in self.codes
