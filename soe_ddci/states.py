"""Finite state space for a Single Objective Entity.

States S0..S9 as defined in the SOE-DDCI specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Set


class State(Enum):
    """Primary entity states."""

    NULL = "NULL"           # S0  No active representation
    CREATED = "CREATED"     # S1  Entity initialized
    ACTIVE = "ACTIVE"       # S2  Currently processing
    OBSERVED = "OBSERVED"   # S3  Receiving new information
    RELATED = "RELATED"     # S4  Connected to another entity
    STORED = "STORED"       # S5  Written into a data bank
    RETRIEVED = "RETRIEVED" # S6  Historical data recalled
    TRANSFORMED = "TRANSFORMED"  # S7  State changed by mechanism
    ARCHIVED = "ARCHIVED"   # S8  Historical / inactive
    INVALID = "INVALID"     # S9  Contradiction or failed validation

    @property
    def id(self) -> str:
        return f"S{list(State).index(self)}"


@dataclass(frozen=True)
class StateTransition:
    """A single allowed transition between two states."""

    from_state: State
    to_state: State
    condition: str = ""  # optional guard description

    def __post_init__(self) -> None:
        if (self.from_state, self.to_state) not in VALID_TRANSITIONS:
            raise ValueError(
                f"Invalid transition {self.from_state} -> {self.to_state}"
            )


# Allowed edges in the state transition graph.
VALID_TRANSITIONS: FrozenSet = frozenset(
    {
        # NULL -> CREATED
        (State.NULL, State.CREATED),
        # CREATED -> ACTIVE, STORED
        (State.CREATED, State.ACTIVE),
        (State.CREATED, State.STORED),
        # ACTIVE <-> OBSERVED, ACTIVE -> RELATED
        (State.ACTIVE, State.OBSERVED),
        (State.OBSERVED, State.ACTIVE),
        (State.ACTIVE, State.RELATED),
        # STORED -> RETRIEVED, OBSERVED -> STORED
        (State.STORED, State.RETRIEVED),
        (State.OBSERVED, State.STORED),
        # RETRIEVED -> TRANSFORMED, RELATED -> TRANSFORMED
        (State.RETRIEVED, State.TRANSFORMED),
        (State.RELATED, State.TRANSFORMED),
        # TRANSFORMED -> ACTIVE, ARCHIVED, INVALID
        (State.TRANSFORMED, State.ACTIVE),
        (State.TRANSFORMED, State.ARCHIVED),
        (State.TRANSFORMED, State.INVALID),
        # TERMINAL sinks
        (State.ACTIVE, State.ARCHIVED),
        (State.STORED, State.ARCHIVED),
    }
)


def available_from(state: State) -> List[State]:
    """Return all states reachable in one step from `state`."""
    return sorted(
        {to for (fr, to) in VALID_TRANSITIONS if fr == state},
        key=lambda s: s.id,
    )


def is_terminal(state: State) -> bool:
    """A terminal state has no outgoing transitions."""
    return not any(fr == state for (fr, _) in VALID_TRANSITIONS)


# All states, ordered by ID.
ALL_STATES: List[State] = sorted(list(State), key=lambda s: s.id)