from __future__ import annotations

from decimal import Decimal, InvalidOperation

from beartype import beartype


@beartype
def parse_inventory_form_qty(raw: str) -> Decimal:
    """Parse technician qty text: letters are ignored (``15с`` → ``15``).

    Digits, sign, decimal separators and other non-letters are kept; commas become
    dots; spaces are stripped. Empty/non-numeric after cleanup raises ``ValueError``.
    """
    cleaned = "".join(ch for ch in raw.strip() if not ch.isalpha())
    cleaned = cleaned.replace(",", ".").replace(" ", "")
    if not cleaned:
        raise ValueError("quantity text has no digits")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("quantity text is not a number") from error
