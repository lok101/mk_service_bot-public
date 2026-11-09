from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.agent_recovery_permit_lib.models import PermitOperation, new_permit
from scripts.agent_recovery_permit_lib.store import (
    PermitConsumedError,
    PermitExpiredError,
    PermitMismatchError,
    consume_permit,
    issue_permit,
)


def test_issue_and_consume_permit_roundtrip(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    permit = new_permit(
        issuer="agent_worktree.remove",
        source_report_id="apr-11111111-1111-1111-1111-111111111111",
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(tmp_path / "lane"),),
        preconditions=("unregistered",),
        job_id="job-abc",
        conversation_id="conv-1",
        permit_id="arp-11111111-1111-1111-1111-111111111111",
    )
    issued = issue_permit(common, permit)
    assert (common / "agent-recovery-permits" / "active" / f"{issued.permit_id}.json").is_file()
    consumed = consume_permit(
        common,
        issued.permit_id,
        job_id="job-abc",
        conversation_id="conv-1",
    )
    assert consumed.permit_id == issued.permit_id
    assert not (common / "agent-recovery-permits" / "active" / f"{issued.permit_id}.json").exists()
    assert (common / "agent-recovery-permits" / "consumed" / f"{issued.permit_id}.json").is_file()


def test_expired_permit_rejected(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    issued_at = datetime.now(UTC) - timedelta(minutes=30)
    permit = new_permit(
        issuer="agent_worktree.remove",
        source_report_id="apr-22222222-2222-2222-2222-222222222222",
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(tmp_path / "lane"),),
        preconditions=(),
        permit_id="arp-22222222-2222-2222-2222-222222222222",
        issued_at=issued_at,
        ttl=timedelta(minutes=10),
    )
    issue_permit(common, permit)
    with pytest.raises(PermitExpiredError):
        consume_permit(common, permit.permit_id)


def test_reuse_after_consume_rejected(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    permit = new_permit(
        issuer="lane_closeout.orchestration",
        source_report_id="apr-33333333-3333-3333-3333-333333333333",
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(tmp_path / "lane"),),
        preconditions=(),
        permit_id="arp-33333333-3333-3333-3333-333333333333",
    )
    issue_permit(common, permit)
    consume_permit(common, permit.permit_id)
    with pytest.raises(PermitConsumedError):
        consume_permit(common, permit.permit_id)


def test_conversation_mismatch_rejected(tmp_path: Path) -> None:
    common = tmp_path / "g"
    common.mkdir()
    permit = new_permit(
        issuer="agent_lane_overlap.cleanup",
        source_report_id="apr-44444444-4444-4444-4444-444444444444",
        operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
        target_paths=(str(tmp_path / "lane"),),
        preconditions=(),
        conversation_id="conv-a",
        permit_id="arp-44444444-4444-4444-4444-444444444444",
    )
    issue_permit(common, permit)
    with pytest.raises(PermitMismatchError):
        consume_permit(common, permit.permit_id, conversation_id="conv-b")


def test_unknown_issuer_rejected() -> None:
    with pytest.raises(ValueError, match="unknown issuer"):
        new_permit(
            issuer="skill.prose",
            source_report_id="apr-55555555-5555-5555-5555-555555555555",
            operation=PermitOperation.REMOVE_UNREGISTERED_LANE_RESIDUE,
            target_paths=("/tmp/x",),
            preconditions=(),
        )
