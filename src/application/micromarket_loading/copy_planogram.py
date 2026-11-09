from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.master_data import MachineKind, MasterMachineStore
from src.application.micromarket_loading.planogram import MicromarketPlanogram
from src.application.micromarket_loading.ports import MicromarketPlanogramStore
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketPlanogramCopyRejected(Exception):
    message: str
    code: str

    def __str__(self) -> str:
        return self.message


@beartype
@dataclass(frozen=True, slots=True)
class CopyMicromarketPlanogramInput:
    source_machine_code: str
    dest_machine_code: str


@beartype
@dataclass(slots=True)
class CopyMicromarketPlanogram:
    store: MicromarketPlanogramStore
    machines: MasterMachineStore
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    @beartype
    def execute(self, input: CopyMicromarketPlanogramInput) -> MicromarketPlanogram:
        source_code = input.source_machine_code.strip()
        dest_code = input.dest_machine_code.strip()
        if not source_code:
            raise MicromarketPlanogramCopyRejected(
                "source_machine_code must be non-empty",
                code="empty_copy_source",
            )
        if source_code == dest_code:
            raise MicromarketPlanogramCopyRejected(
                "source and dest machine_code must differ",
                code="copy_same_machine",
            )

        source_machine = self.machines.get(MachineId(source_code))
        if source_machine is None or source_machine.kind is not MachineKind.MICRO_MARKET:
            raise MicromarketPlanogramCopyRejected(
                f"source machine {source_code!r} is not micromarket",
                code="source_not_micromarket",
            )
        dest_machine = self.machines.get(MachineId(dest_code))
        if dest_machine is None or dest_machine.kind is not MachineKind.MICRO_MARKET:
            raise MicromarketPlanogramCopyRejected(
                f"dest machine {dest_code!r} is not micromarket",
                code="dest_not_micromarket",
            )

        source_doc = self.store.get(source_code)
        if source_doc is None:
            raise MicromarketPlanogramCopyRejected(
                f"source planogram missing for {source_code!r}",
                code="source_planogram_missing",
            )

        doc = MicromarketPlanogram(
            machine_code=dest_code,
            lines=source_doc.lines,
            updated_at=self.now_factory(),
            shop_list_status=ShopListPublishStatus.UNPUBLISHED,
            shop_list_error="",
            shop_list_publication_id="",
            shop_list_catch_up_requested=False,
            shelves=source_doc.shelves,
        )
        self.store.upsert(doc)
        return doc
