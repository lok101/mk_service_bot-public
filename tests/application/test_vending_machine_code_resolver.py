from __future__ import annotations

from src.application.inventory_reconciliation.resolvers import (
    IdentityVendingMachineCodeResolver,
    MappingVendingMachineCodeResolver,
)
from src.domain.ids import MachineId


def test_identity_resolver_strips_whitespace() -> None:
    resolver = IdentityVendingMachineCodeResolver()
    assert resolver.resolve("  VM01  ") == MachineId("VM01")


def test_identity_resolver_rejects_blank_code() -> None:
    resolver = IdentityVendingMachineCodeResolver()
    assert resolver.resolve("   ") is None
    assert resolver.resolve("") is None


def test_mapping_resolver_looks_up_exact_key() -> None:
    resolver = MappingVendingMachineCodeResolver({"VM01": MachineId("vm-01")})
    assert resolver.resolve("VM01") == MachineId("vm-01")
    assert resolver.resolve("  VM01  ") is None
