from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from beartype import beartype

from src.application.master_data.companies import KitPlatform


@beartype
def _account_key_slug(*, name: str | None, login: str) -> str:
    base = (name or login).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return f"vending-{slug or login.strip().lower()}"


@beartype
def generate_platform_accounts_from_legacy(*, legacy_path: Path, output_path: Path) -> None:
    raw_text = legacy_path.read_text(encoding="utf-8")
    decoded: Any = json.loads(raw_text)
    if not isinstance(decoded, list):
        raise ValueError(f"Ожидался JSON-массив аккаунтов в {legacy_path}")
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(decoded):
        if not isinstance(entry, dict):
            raise ValueError(f"Элемент аккаунта #{index} должен быть объектом в {legacy_path}")
        login = str(entry.get("login", "")).strip()
        password = str(entry.get("password", "")).strip()
        if not login:
            raise ValueError(f"Поле login обязательно для аккаунта #{index} в {legacy_path}")
        if not password:
            raise ValueError(f"Поле password обязательно для аккаунта #{index} в {legacy_path}")
        if "company_id" not in entry:
            raise ValueError(f"Поле company_id обязательно для аккаунта #{index} в {legacy_path}")
        company_id = int(entry["company_id"])
        name_raw = entry.get("name")
        name = str(name_raw).strip() if name_raw is not None else None
        if name == "":
            name = None
        rows.append(
            {
                "account_key": _account_key_slug(name=name, login=login),
                "company_id": company_id,
                "platform": KitPlatform.KIT_VENDING.value,
                "kit_company_id": company_id,
                "role": "sales_poll" if index == 0 else "catalog",
                "login": login,
                "password": password,
            },
        )
    output_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
