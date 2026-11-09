from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beartype import beartype
from pydantic import SecretStr

from src.application.master_data.companies import KitPlatform, KitPlatformRole

_LOGGER = logging.getLogger(__name__)

_PLATFORM_BY_VALUE: dict[str, KitPlatform] = {item.value: item for item in KitPlatform}
_ROLE_BY_VALUE: dict[str, KitPlatformRole] = {item.value: item for item in KitPlatformRole}


@beartype
@dataclass(frozen=True, slots=True)
class KitPlatformAccount:
    account_key: str
    company_id: int
    platform: KitPlatform
    kit_company_id: int
    role: KitPlatformRole
    login: str
    password: SecretStr

    @property
    def label(self) -> str:
        return f"{self.login} (kit_company_id={self.kit_company_id})"


@beartype
def load_kit_platform_accounts(path: Path) -> list[KitPlatformAccount]:
    raw = path.read_text(encoding="utf-8")
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, list):
        raise ValueError(f"Ожидался JSON-массив аккаунтов в {path}")
    if not decoded:
        raise ValueError(f"Список аккаунтов пуст в {path}")

    result: list[KitPlatformAccount] = []
    for index, entry in enumerate(decoded):
        if not isinstance(entry, dict):
            raise ValueError(f"Элемент аккаунта #{index} должен быть объектом в {path}")
        row: dict[str, Any] = entry

        account_key = str(row.get("account_key", "")).strip()
        if not account_key:
            raise ValueError(f"Поле account_key обязательно для аккаунта #{index} в {path}")

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

        if "kit_company_id" not in row:
            raise ValueError(f"Поле kit_company_id обязательно для аккаунта #{index} в {path}")
        try:
            kit_company_id = int(row["kit_company_id"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Поле kit_company_id должно быть целым числом для аккаунта #{index} в {path}",
            ) from exc

        platform_raw = str(row.get("platform", "")).strip()
        if not platform_raw:
            raise ValueError(f"Поле platform обязательно для аккаунта #{index} в {path}")
        platform = _PLATFORM_BY_VALUE.get(platform_raw)
        if platform is None:
            raise ValueError(
                f"Неизвестная platform {platform_raw!r} для аккаунта #{index} в {path}",
            )

        role_raw = str(row.get("role", "")).strip()
        if not role_raw:
            raise ValueError(f"Поле role обязательно для аккаунта #{index} в {path}")
        role = _ROLE_BY_VALUE.get(role_raw)
        if role is None:
            raise ValueError(f"Неизвестная role {role_raw!r} для аккаунта #{index} в {path}")

        result.append(
            KitPlatformAccount(
                account_key=account_key,
                company_id=company_id,
                platform=platform,
                kit_company_id=kit_company_id,
                role=role,
                login=login,
                password=SecretStr(password),
            ),
        )
    return result


@beartype
def accounts_file_is_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        load_kit_platform_accounts(path)
    except OSError, ValueError, json.JSONDecodeError:
        return False
    return True
