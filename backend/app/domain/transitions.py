"""Command lifecycle state transitions.

Pure validation only — no persistence or command execution.
"""

from __future__ import annotations

from backend.app.domain.enums import CommandState, DomainErrorCode
from backend.app.domain.errors import DomainValidationError

ALLOWED_TRANSITIONS: dict[CommandState, frozenset[CommandState]] = {
    CommandState.RECEIVED: frozenset(
        {CommandState.PARSED, CommandState.REJECTED},
    ),
    CommandState.PARSED: frozenset(
        {CommandState.RESOLVING, CommandState.REJECTED},
    ),
    CommandState.RESOLVING: frozenset(
        {
            CommandState.AWAITING_CLARIFICATION,
            CommandState.PLANNED,
            CommandState.REJECTED,
            CommandState.FAILED,
        },
    ),
    CommandState.AWAITING_CLARIFICATION: frozenset(
        {CommandState.RESOLVING, CommandState.REJECTED},
    ),
    CommandState.PLANNED: frozenset(
        {CommandState.AWAITING_CONFIRMATION, CommandState.REJECTED},
    ),
    CommandState.AWAITING_CONFIRMATION: frozenset(
        {CommandState.APPLYING, CommandState.REJECTED},
    ),
    CommandState.APPLYING: frozenset(
        {
            CommandState.VERIFIED,
            CommandState.PARTIALLY_APPLIED,
            CommandState.FAILED,
        },
    ),
    CommandState.VERIFIED: frozenset({CommandState.REVERTED}),
    CommandState.PARTIALLY_APPLIED: frozenset({CommandState.REVERTED}),
    CommandState.REJECTED: frozenset(),
    CommandState.FAILED: frozenset(),
    CommandState.REVERTED: frozenset(),
}


def validate_transition(current: CommandState, target: CommandState) -> None:
    """Raise when ``current -> target`` is not an allowed lifecycle transition."""
    if current == target:
        raise DomainValidationError(
            f"Same-state transition is not allowed: {current.value}",
            code=DomainErrorCode.INVALID_STATE_TRANSITION,
            field="state",
        )
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise DomainValidationError(
            f"Invalid command state transition: {current.value} -> {target.value}",
            code=DomainErrorCode.INVALID_STATE_TRANSITION,
            field="state",
        )
