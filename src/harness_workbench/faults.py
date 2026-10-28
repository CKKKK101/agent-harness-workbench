from __future__ import annotations

import os

from .store import Store


class InjectedCrash(BaseException):
    """Not an Exception: an agent must not turn a simulated process death into tool output."""


class RecoveryConflict(Exception):
    """A durable intent disagrees with the current workspace; do not overwrite it."""


class UncertainExecution(Exception):
    """The previous test process may have caused effects; explicit retry is required."""


class FaultInjector:
    def __init__(self, store: Store, task_id: str, *, hard: bool = False):
        self.store, self.task_id, self.hard = store, task_id, hard

    def hit(self, point: str):
        if self.store.consume_fault(self.task_id, point):
            self.store.event(self.task_id, "fault.injected", {"point": point, "hard": self.hard})
            if self.hard:
                os._exit(86)  # Only used by explicitly invoked evaluation subprocesses.
            raise InjectedCrash(point)
