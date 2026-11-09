from __future__ import annotations

from pathlib import Path

import pytest
from scripts.agent_job_lib.resources import (
    ResourceClaimError,
    allocate_resources,
    claim_ports,
    claim_slug,
    release_slug_claim,
    short_id_from_job_id,
)


def test_short_id_from_job_id() -> None:
    assert short_id_from_job_id("job-deadbeefcafebabe") == "deadbeef"


def test_allocate_resources_shape(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    resources = allocate_resources(
        git_common_dir=common,
        job_id="job-deadbeefcafebabe",
        ports=(18080,),
    )
    assert resources["compose_project"] == "mk_service_bot_deadbeef"
    assert resources["tmp_root"].startswith(str(common / "agent-jobs" / "job-deadbeefcafebabe"))
    assert resources["ports"] == [18080]


def test_claim_slug_exclusive(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    claim_slug(common, "demo-slug", job_id="job-aaa")
    with pytest.raises(ResourceClaimError, match="slug"):
        claim_slug(common, "demo-slug", job_id="job-bbb")
    release_slug_claim(common, "demo-slug")
    claim_slug(common, "demo-slug", job_id="job-bbb")


def test_claim_ports_exclusive(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    claim_ports(common, (19090,), job_id="job-aaa")
    with pytest.raises(ResourceClaimError, match="port"):
        claim_ports(common, (19090,), job_id="job-bbb")
