"""The call state machine, shared by occurrences and attempts (`CallState`).

queued -> dispatching -> ringing -> connected -> completed is the happy path. `scheduled` is the
resting state of an occurrence the scheduler created. A queued call that finds no free slot goes
back to `scheduled`. `unknown` means we lost track (crash mid-dispatch, no end signal); it is
never auto-redialled because the call may have rung.
"""

from sg_core.models.enums import CallState as S

TERMINAL: frozenset[S] = frozenset(
    {S.COMPLETED, S.BUSY, S.UNANSWERED, S.FAILED, S.CANCELLED, S.MISSED}
)
# States holding a call slot (and an open budget hold).
ACTIVE: frozenset[S] = frozenset({S.DISPATCHING, S.RINGING, S.CONNECTED})

_ALLOWED: dict[S, frozenset[S]] = {
    S.SCHEDULED: frozenset({S.QUEUED, S.CANCELLED, S.MISSED}),
    S.QUEUED: frozenset({S.SCHEDULED, S.DISPATCHING, S.CANCELLED, S.FAILED, S.MISSED}),
    S.DISPATCHING: frozenset({S.RINGING, S.FAILED, S.UNKNOWN, S.CANCELLED}),
    S.RINGING: frozenset(
        {S.CONNECTED, S.MISSED, S.UNANSWERED, S.BUSY, S.FAILED, S.CANCELLED, S.UNKNOWN}
    ),
    S.CONNECTED: frozenset({S.COMPLETED, S.FAILED, S.UNKNOWN}),
    S.UNKNOWN: frozenset({S.COMPLETED, S.MISSED, S.FAILED}),
}


class InvalidTransition(RuntimeError):
    def __init__(self, current: S, new: S) -> None:
        super().__init__(f"call cannot move from {current.value} to {new.value}")
        self.current = current
        self.new = new


def can_transition(current: S, new: S) -> bool:
    return new in _ALLOWED.get(current, frozenset())


def require_transition(current: S, new: S) -> None:
    if not can_transition(current, new):
        raise InvalidTransition(current, new)
