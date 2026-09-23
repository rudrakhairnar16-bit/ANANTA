import threading
import time
from enum import Enum
from typing import Protocol


class StageOutcome(str, Enum):
    """Structured execution outcome for a stage attempt.

    ``StageOutcome`` is deliberately separate from ``StageStatus``. A timed-out
    stage is reported through the lifecycle status ``StageStatus.CANCELLED``
    while the execution outcome is ``StageOutcome.TIMEOUT``; an operator
    cancel is ``StageOutcome.CANCELLED``. This keeps ``TIMEOUT`` out of the
    lifecycle state machine (M6 contract) while still letting callers
    distinguish why a stage stopped.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Clock(Protocol):
    """Injected clock used for deadline bookkeeping.

    Production uses :class:`MonotonicClock`; tests inject a
    :class:`FakeClock` for deterministic timeout simulation.
    """

    def now(self) -> float:
        ...


class MonotonicClock:
    """Wall-clock implementation backed by ``time.perf_counter``.

    ``perf_counter`` is monotonic and immune to system clock adjustments.
    """

    def now(self) -> float:
        return time.perf_counter()


class FakeClock:
    """Scripted monotonic clock for deterministic timeout tests."""

    def __init__(self, start: float = 0.0):
        self._value = float(start)
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._value

    def advance(self, delta: float) -> float:
        """Advance the clock by ``delta`` seconds and return the new value."""
        with self._lock:
            self._value += float(delta)
            return self._value

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


class CancellationToken:
    """Thread-safe cooperative cancellation signal for one stage attempt.

    Cancellation is cooperative: the worker polls :meth:`is_cancelled` (or
    blocks on :meth:`wait`) and stops when safe. No thread is ever killed.
    """

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None

    def cancel(self, reason: str = "cancelled") -> None:
        """Signal cancellation. The first reason wins."""
        with self._lock:
            if self._reason is None:
                self._reason = reason
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout=timeout)
