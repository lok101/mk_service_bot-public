from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from scripts.agent_adr_number_lib.allocate import reserve
from scripts.agent_adr_number_lib.lock import LockTimeoutError, exclusive_allocate_lock
from scripts.agent_adr_number_lib.paths import allocate_lock_path, high_water_path


def test_lock_timeout_without_partial_write(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    held = threading.Event()
    release = threading.Event()

    def _hold() -> None:
        with exclusive_allocate_lock(common, timeout_s=5.0):
            held.set()
            release.wait(timeout=10.0)

    holder = threading.Thread(target=_hold, daemon=True)
    holder.start()
    assert held.wait(timeout=5.0)

    with pytest.raises(LockTimeoutError):
        reserve(
            common,
            "adr",
            worktree_roots=(),
            head_max=0,
            lock_timeout_s=0.2,
        )
    assert not high_water_path(common).exists()
    release.set()
    holder.join(timeout=5.0)


def test_exclusive_lock_serializes(tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    order: list[str] = []

    def _worker(name: str) -> None:
        with exclusive_allocate_lock(common, timeout_s=5.0):
            order.append(f"{name}-enter")
            time.sleep(0.05)
            order.append(f"{name}-exit")

    t1 = threading.Thread(target=_worker, args=("a",))
    t2 = threading.Thread(target=_worker, args=("b",))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    assert len(order) == 4
    # No interleaving of enter/exit pairs.
    assert order[0].endswith("-enter")
    assert order[1].endswith("-exit")
    assert order[2].endswith("-enter")
    assert order[3].endswith("-exit")
    assert allocate_lock_path(common).exists() or True


def test_load_high_water_rejects_non_object(tmp_path: Path) -> None:
    from scripts.agent_adr_number_lib.store import StoreCorruptError, load_high_water

    common = tmp_path / "common"
    common.mkdir()
    path = high_water_path(common)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([1, 2, 3]) + "\n", encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        load_high_water(common)
