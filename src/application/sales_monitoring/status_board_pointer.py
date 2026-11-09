from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from beartype import beartype

STATUS_BOARD_POINTER_ID = "ops_no_sales"

__all__ = [
    "STATUS_BOARD_POINTER_ID",
    "StatusBoardPointer",
]


@beartype
@dataclass(frozen=True, slots=True)
class StatusBoardPointer:
    chat_id: int
    message_id: int
    posted_at: datetime
    last_text: str
