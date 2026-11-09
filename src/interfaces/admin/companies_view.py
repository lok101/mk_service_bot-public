from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

from src.application.master_data import (
    CompanyStore,
    CompanyValidationError,
    KitPlatform,
    KitPlatformBinding,
    KitPlatformRole,
    MasterCompany,
)

CompanyListStatus = Literal["active", "inactive", "all"]


@beartype
@dataclass(frozen=True, slots=True)
class CompanyRowView:
    company_id: int
    name: str
    is_active: bool
    bindings_summary: str
    status_label: str


@beartype
@dataclass(frozen=True, slots=True)
class CompaniesListView:
    rows: tuple[CompanyRowView, ...]
    status: CompanyListStatus


@beartype
@dataclass(frozen=True, slots=True)
class CompanyBindingRowView:
    platform: str
    kit_company_id: str
    roles: frozenset[str]


@beartype
@dataclass(frozen=True, slots=True)
class CompanyFormView:
    company_id: int | None
    name: str
    is_active: bool
    bindings: tuple[CompanyBindingRowView, ...]


@beartype
def parse_company_list_status(raw: str | None) -> CompanyListStatus:
    if raw == "inactive":
        return "inactive"
    if raw == "all":
        return "all"
    return "active"


@beartype
def format_bindings_summary(bindings: tuple[KitPlatformBinding, ...]) -> str:
    parts: list[str] = []
    for binding in bindings:
        short = "vending" if binding.platform is KitPlatform.KIT_VENDING else "shop"
        role_bits = []
        for role in binding.roles:
            if role is KitPlatformRole.SALES_POLL:
                role_bits.append("poll")
            elif role is KitPlatformRole.CATALOG:
                role_bits.append("catalog")
            else:
                role_bits.append(role.value)
        roles_s = ",".join(role_bits)
        parts.append(f"{short}:{binding.kit_company_id} [{roles_s}]")
    return "; ".join(parts)


@beartype
def build_companies_list_view(
    store: CompanyStore,
    *,
    status: CompanyListStatus,
) -> CompaniesListView:
    rows = tuple(
        CompanyRowView(
            company_id=c.company_id,
            name=c.name,
            is_active=c.is_active,
            bindings_summary=format_bindings_summary(c.platform_bindings),
            status_label="да" if c.is_active else "нет",
        )
        for c in sorted(store.list_all(), key=lambda item: item.name.casefold())
        if _matches_status(c, status)
    )
    return CompaniesListView(rows=rows, status=status)


@beartype
def build_company_form_view(company: MasterCompany | None) -> CompanyFormView:
    if company is None:
        return CompanyFormView(company_id=None, name="", is_active=True, bindings=())
    return CompanyFormView(
        company_id=company.company_id,
        name=company.name,
        is_active=company.is_active,
        bindings=tuple(
            CompanyBindingRowView(
                platform=b.platform.value,
                kit_company_id=str(b.kit_company_id),
                roles=frozenset(r.value for r in b.roles),
            )
            for b in company.platform_bindings
        ),
    )


def _matches_status(company: MasterCompany, status: CompanyListStatus) -> bool:
    if status == "all":
        return True
    if status == "active":
        return company.is_active
    return not company.is_active


def _binding_row_indices(fields: dict[str, str]) -> list[int]:
    indices: set[int] = set()
    for key in fields:
        for prefix in ("platform-", "kit_company_id-"):
            rest = key[len(prefix) :] if key.startswith(prefix) else ""
            if rest.isdigit():
                indices.add(int(rest))
    return sorted(indices)


@beartype
def bindings_from_form(fields: dict[str, str]) -> tuple[KitPlatformBinding, ...]:
    result: list[KitPlatformBinding] = []
    for index in _binding_row_indices(fields):
        platform_raw = fields.get(f"platform-{index}", "").strip()
        kit_raw = fields.get(f"kit_company_id-{index}", "").strip()
        if not platform_raw and not kit_raw:
            continue
        if not platform_raw or not kit_raw:
            raise CompanyValidationError(f"incomplete binding row {index}")
        roles: list[KitPlatformRole] = []
        for role in KitPlatformRole:
            if fields.get(f"role-{role.value}-{index}"):
                roles.append(role)
        try:
            platform = KitPlatform(platform_raw)
            kit_company_id = int(kit_raw)
        except ValueError as exc:
            raise CompanyValidationError(f"invalid binding row {index}") from exc
        result.append(
            KitPlatformBinding(
                platform=platform,
                kit_company_id=kit_company_id,
                roles=tuple(roles),
            )
        )
    return tuple(result)
