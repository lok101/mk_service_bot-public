from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.agent_defect_observation_lib.models import new_observation
from scripts.agent_defect_observation_lib.paths import (
    AdoStoreUnavailableError,
    default_defect_observations_root,
    default_product_id,
    home_defect_observations_root,
    load_platform_home,
)
from scripts.agent_defect_observation_lib.store import (
    create_observation,
    list_observations,
    load_observation,
)


def _write_kernel_ref(product: Path, home: Path) -> None:
    product.mkdir(parents=True, exist_ok=True)
    (product / "kernel_ref").write_text(
        json.dumps({"home": str(home), "ref": "test", "mount": {}}),
        encoding="utf-8",
    )


def test_create_get_list_under_home(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    (product / "AGENT-OVERLAY.md").write_text("# Overlay mk_service_bot\n", encoding="utf-8")

    store_root = default_defect_observations_root(product)
    assert store_root == home_defect_observations_root(home)

    obs = new_observation(
        product_id=default_product_id(product),
        source="chat_cli",
        signature="sig-admin-deps",
        summary="admin deps bag",
        related_finding_ref="docs/repository-review/r1/findings/F001.md",
    )
    created = create_observation(store_root, obs)
    assert created.product_id == "mk_service_bot"
    assert created.class_ == "error"

    loaded = load_observation(store_root, created.observation_id)
    assert loaded.observation_id == created.observation_id
    assert (store_root / "reports").is_dir()

    listed = list_observations(store_root, product_id="mk_service_bot")
    assert len(listed) == 1
    assert listed[0].observation_id == created.observation_id


def test_idempotent_finding_key(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)

    store_root = default_defect_observations_root(product)
    finding = "docs/repository-review/r1/findings/F002.md"
    first = create_observation(
        store_root,
        new_observation(
            product_id="mk",
            source="repository_review",
            signature="dup",
            summary="one",
            related_finding_ref=finding,
        ),
    )
    second = create_observation(
        store_root,
        new_observation(
            product_id="mk",
            source="repository_review",
            signature="dup-again",
            summary="two",
            related_finding_ref=finding,
        ),
    )
    assert second.observation_id == first.observation_id
    assert len(list_observations(store_root)) == 1


def test_missing_kernel_ref_fail_closed(tmp_path: Path) -> None:
    product = tmp_path / "bare"
    product.mkdir()
    with pytest.raises(AdoStoreUnavailableError):
        load_platform_home(product)


def test_redacts_secret_like_summary(tmp_path: Path) -> None:
    home = tmp_path / "agent_platform"
    home.mkdir()
    product = tmp_path / "mk"
    _write_kernel_ref(product, home)
    store_root = default_defect_observations_root(product)
    created = create_observation(
        store_root,
        new_observation(
            product_id="mk",
            source="chat_cli",
            signature="sig",
            summary="token=super-secret-value should hide",
        ),
    )
    assert "super-secret-value" not in created.summary
    assert "[REDACTED]" in created.summary
