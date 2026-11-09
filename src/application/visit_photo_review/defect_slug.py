from __future__ import annotations

import re

from beartype import beartype

_CYRILLIC_TO_LATIN: dict[str, str] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}
_NON_SLUG = re.compile(r"[^a-z0-9]+")


@beartype
def defect_code_from_label(label: str) -> str:
    """Stable ASCII slug from a defect label (translit → slug)."""
    chars: list[str] = []
    for char in label.strip().casefold():
        chars.append(_CYRILLIC_TO_LATIN.get(char, char))
    slug = _NON_SLUG.sub("-", "".join(chars)).strip("-")
    return slug or "problem"
