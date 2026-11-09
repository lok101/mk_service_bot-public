from __future__ import annotations

from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.snack_loading.ports import KitMatrixDeployMapStore


@runtime_checkable
class KitMatrixDeployResultView(Protocol):
    @property
    def logical_matrix_name(self) -> str: ...

    @property
    def machine_code(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def kit_matrix_id(self) -> int | None: ...


@beartype
def record_kit_matrix_deploy(
    store: KitMatrixDeployMapStore,
    *,
    result: KitMatrixDeployResultView,
    vending_machine_id: int | None,
    kit_matrix_name: str | None,
) -> None:
    if result.status != "applied" or result.kit_matrix_id is None:
        return
    store.upsert(
        kit_matrix_id=result.kit_matrix_id,
        logical_matrix_name=result.logical_matrix_name,
        machine_code=result.machine_code,
        vending_machine_id=vending_machine_id,
        kit_matrix_name=kit_matrix_name,
    )
