from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class Result[T, E]:
    _value: T | None = None
    _error: E | None = None

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        return cls(_value=value, _error=None)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        return cls(_value=None, _error=error)

    def is_ok(self) -> bool:
        return self._error is None

    def is_err(self) -> bool:
        return self._error is not None

    @property
    def value(self) -> T:
        if self._error is not None:
            msg = "Result is error"
            raise ValueError(msg)
        if self._value is None:
            msg = "Result value is missing"
            raise ValueError(msg)
        return self._value

    @property
    def error(self) -> E:
        if self._error is None:
            msg = "Result is ok"
            raise ValueError(msg)
        return self._error
