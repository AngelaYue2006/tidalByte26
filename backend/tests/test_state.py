"""Issue #5: the status list matches docs/ARCHITECTURE.md and transition() refuses illegal moves."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from app.state import (
    STATUSES,
    TERMINAL,
    TRANSITIONS,
    IllegalTransition,
    can_transition,
    transition,
)

DOC_STATUSES = [
    "intake", "calendar", "places", "calling", "ranking", "awaiting_approval",
    "booking", "transport", "awaiting_contact", "completed", "failed", "cancelled",
]


@dataclass
class FakeTask:
    id: str = "t1"
    status: str = "intake"
    updated_at: datetime = field(default_factory=lambda: datetime(2000, 1, 1, tzinfo=UTC))


def test_status_list_matches_architecture_doc():
    assert list(STATUSES) == DOC_STATUSES
    assert set(TRANSITIONS) == set(STATUSES)


def test_happy_path_walks_every_step_in_order():
    task = FakeTask()
    for nxt in DOC_STATUSES[1:9] + ["completed"]:
        before = task.updated_at
        transition(task, nxt)
        assert task.status == nxt
        assert task.updated_at >= before


def test_transport_may_skip_contact_when_a_ride_is_available():
    assert can_transition("transport", "completed")
    assert can_transition("transport", "awaiting_contact")


@pytest.mark.parametrize("frm", [s for s in DOC_STATUSES if s not in TERMINAL])
def test_every_live_status_can_fail_or_be_cancelled(frm):
    assert can_transition(frm, "failed")
    assert can_transition(frm, "cancelled")


@pytest.mark.parametrize("terminal", sorted(TERMINAL))
def test_terminal_statuses_go_nowhere(terminal):
    assert TRANSITIONS[terminal] == frozenset()
    with pytest.raises(IllegalTransition):
        transition(FakeTask(status=terminal), "intake")


@pytest.mark.parametrize(
    "frm,to",
    [
        ("intake", "booking"),             # skipping steps
        ("ranking", "calling"),            # going backwards
        ("awaiting_approval", "transport"),  # booking before approval is complete
        ("intake", "completed"),           # never a silent completed
        ("calling", "calling"),            # no self-loop
    ],
)
def test_illegal_moves_raise_and_leave_the_task_untouched(frm, to):
    task = FakeTask(status=frm)
    with pytest.raises(IllegalTransition, match=f"from '{frm}' to '{to}'"):
        transition(task, to)
    assert task.status == frm


def test_unknown_status_names_raise():
    with pytest.raises(IllegalTransition, match="unknown status"):
        transition(FakeTask(), "booked")
    with pytest.raises(IllegalTransition, match="unknown status"):
        transition(FakeTask(status="limbo"), "calendar")
