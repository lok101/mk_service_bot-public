from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class LegacyKitVendingAccountRow:
    index: int
    company_id: int
    login: str
    name: str | None = None


@beartype
def load_legacy_kitvending_accounts(path: Path) -> tuple[LegacyKitVendingAccountRow, ...]:
    raw = path.read_text(encoding="utf-8")
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, list):
        raise ValueError(f"Ожидался JSON-массив аккаунтов в {path}")
    if not decoded:
        raise ValueError(f"Список аккаунтов пуст в {path}")

    result: list[LegacyKitVendingAccountRow] = []
    for index, entry in enumerate(decoded):
        if not isinstance(entry, dict):
            raise ValueError(f"Элемент аккаунта #{index} должен быть объектом в {path}")
        row: dict[str, Any] = entry
        login = str(row.get("login", "")).strip()
        password = str(row.get("password", "")).strip()
        if not login:
            raise ValueError(f"Поле login обязательно для аккаунта #{index} в {path}")
        if not password:
            raise ValueError(f"Поле password обязательно для аккаунта #{index} в {path}")
        if "company_id" not in row:
            raise ValueError(f"Поле company_id обязательно для аккаунта #{index} в {path}")
        try:
            company_id = int(row["company_id"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Поле company_id должно быть целым числом для аккаунта #{index} в {path}",
            ) from exc
        name_raw = row.get("name")
        name = str(name_raw).strip() if name_raw is not None else None
        if name == "":
            name = None
        result.append(
            LegacyKitVendingAccountRow(
                index=index,
                company_id=company_id,
                login=login,
                name=name,
            ),
        )
    return tuple(result)
