from __future__ import annotations

from src.application.master_data.ports import MasterDataStores


class _FakeStores:
    @property
    def locations(self): ...

    @property
    def machines(self): ...

    @property
    def placements(self): ...

    @property
    def counters(self): ...

    @property
    def audit(self): ...


def test_master_data_stores_protocol_smoke() -> None:
    assert isinstance(_FakeStores(), MasterDataStores)
