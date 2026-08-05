"""Unit tests for command state transitions."""

from __future__ import annotations

import pytest

from backend.app.domain.enums import CommandState, DomainErrorCode
from backend.app.domain.errors import DomainValidationError
from backend.app.domain.transitions import ALLOWED_TRANSITIONS, validate_transition


def test_every_allowed_transition() -> None:
    for current, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CommandState.RECEIVED, CommandState.PLANNED),
        (CommandState.PLANNED, CommandState.APPLYING),
        (CommandState.APPLYING, CommandState.REVERTED),
        (CommandState.REJECTED, CommandState.PARSED),
        (CommandState.FAILED, CommandState.APPLYING),
        (CommandState.REVERTED, CommandState.VERIFIED),
        (CommandState.VERIFIED, CommandState.APPLYING),
        (CommandState.AWAITING_CONFIRMATION, CommandState.PLANNED),
    ],
)
def test_forbidden_transitions(
    current: CommandState,
    target: CommandState,
) -> None:
    with pytest.raises(DomainValidationError) as exc_info:
        validate_transition(current, target)
    assert exc_info.value.code is DomainErrorCode.INVALID_STATE_TRANSITION


def test_same_state_forbidden() -> None:
    with pytest.raises(DomainValidationError) as exc_info:
        validate_transition(CommandState.PLANNED, CommandState.PLANNED)
    assert exc_info.value.code is DomainErrorCode.INVALID_STATE_TRANSITION


def test_terminal_states_have_no_outbound() -> None:
    for state in (
        CommandState.REJECTED,
        CommandState.FAILED,
        CommandState.REVERTED,
    ):
        assert ALLOWED_TRANSITIONS[state] == frozenset()


def test_reversion_from_verified_and_partial() -> None:
    validate_transition(CommandState.VERIFIED, CommandState.REVERTED)
    validate_transition(CommandState.PARTIALLY_APPLIED, CommandState.REVERTED)


def test_cancel_paths_to_rejected() -> None:
    for current in (
        CommandState.RECEIVED,
        CommandState.PARSED,
        CommandState.RESOLVING,
        CommandState.AWAITING_CLARIFICATION,
        CommandState.PLANNED,
        CommandState.AWAITING_CONFIRMATION,
    ):
        validate_transition(current, CommandState.REJECTED)
