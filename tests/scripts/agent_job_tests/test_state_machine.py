from __future__ import annotations

import pytest
from scripts.agent_job_lib.models import JobState
from scripts.agent_job_lib.state_machine import TransitionError, apply_transition, can_transition


def test_happy_path_chain() -> None:
    state = JobState.RESERVED
    for nxt in (
        JobState.LANE_READY,
        JobState.DESIGNING,
        JobState.PLANNING,
        JobState.IMPLEMENTING,
        JobState.REVIEWING,
        JobState.VERIFYING,
        JobState.COMMITTING,
        JobState.READY_FOR_CLOSEOUT,
    ):
        assert can_transition(state, nxt)
        state = apply_transition(state, nxt)
    assert state is JobState.READY_FOR_CLOSEOUT


def test_blocked_from_working_and_resume_to_previous() -> None:
    assert can_transition(JobState.IMPLEMENTING, JobState.BLOCKED)
    blocked = apply_transition(JobState.IMPLEMENTING, JobState.BLOCKED)
    assert blocked is JobState.BLOCKED
    # resume to previous stage after approved input
    assert can_transition(JobState.BLOCKED, JobState.IMPLEMENTING, resume_to=JobState.IMPLEMENTING)
    assert (
        apply_transition(JobState.BLOCKED, JobState.IMPLEMENTING, resume_to=JobState.IMPLEMENTING)
        is JobState.IMPLEMENTING
    )


def test_illegal_skip_raises() -> None:
    assert can_transition(JobState.RESERVED, JobState.COMMITTING) is False
    with pytest.raises(TransitionError, match="illegal"):
        apply_transition(JobState.RESERVED, JobState.COMMITTING)


def test_idempotent_same_state() -> None:
    assert apply_transition(JobState.PLANNING, JobState.PLANNING) is JobState.PLANNING


def test_failed_and_aborted_terminal_rules() -> None:
    assert can_transition(JobState.VERIFYING, JobState.FAILED)
    assert can_transition(JobState.FAILED, JobState.IMPLEMENTING) is False
    assert can_transition(JobState.FAILED, JobState.IMPLEMENTING, retry=True)
    assert can_transition(JobState.ABORTED, JobState.DESIGNING) is False


def test_can_abort_from_blocked() -> None:
    assert can_transition(JobState.BLOCKED, JobState.ABORTED)
    assert apply_transition(JobState.BLOCKED, JobState.ABORTED) is JobState.ABORTED
