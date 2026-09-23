"""M7 retry policy, classification, and deterministic backoff.

A failure is retried only when it is *explicitly* classified as retryable:
the stage raised a :class:`RetryableError`, the raised exception type is
listed in ``retryable_exceptions``, or a custom ``classifier`` callable
returns True. Plain exceptions are never inferred as retryable from their
text, so M7 cannot accidentally retry a programming or data failure.

``max_attempts`` is the TOTAL number of attempts: attempt 1 is the initial
run and every value above 1 is a retry. The backoff for a failed attempt is
``min(max_delay, base_delay * backoff_multiplier ** (failed_attempt - 1))``.
Bounded jitter adds at most ``jitter_fraction * base`` and the final value is
capped by ``max_delay``. Timing stays on the control plane (the scheduler
loop) so backoff never occupies a worker thread.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class RetryableError(Exception):
    """Marker exception: an explicit, self-describing retryable failure.

    Raising :class:`RetryableError` (or a subclass) opts an attempt into
    retry without requiring any text heuristics. Keep the message stable;
    it is surfaced as the attempt's ``error``.
    """


class JitterMode(str, Enum):
    """Jitter strategy applied to the exponential backoff delay."""

    NONE = "none"
    BOUNDED = "bounded"


class JitterSource(Protocol):
    """Injected source of jitter fractions in the half-open interval."""

    def sample(self) -> float:
        ...


class DefaultJitterSource:
    """Seeded ``random.Random`` source; deterministic for a fixed seed."""

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def sample(self) -> float:
        return self._rng.random()


class ScriptedJitterSource:
    """Scripted sequence of fractions for deterministic jitter tests.

    Each ``sample`` advances one step through ``fractions``, wrapping around
    at the end of the sequence.
    """

    def __init__(self, fractions: Sequence[float]):
        if not fractions:
            raise ValueError("fractions must not be empty")
        self._fractions = tuple(float(f) for f in fractions)
        if any(not 0.0 <= f <= 1.0 for f in self._fractions):
            raise ValueError("jitter fractions must be within [0.0, 1.0]")
        self._index = 0

    def sample(self) -> float:
        fraction = self._fractions[self._index % len(self._fractions)]
        self._index += 1
        return fraction


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable retry + backoff configuration for one execution engine.

    ``max_attempts`` counts the initial attempt plus retries. ``base_delay``
    is the delay after the first failure; each subsequent failed attempt
    multiplies the running backoff by ``backoff_multiplier`` until
    ``max_delay`` caps it.
    """

    max_attempts: int = 1
    base_delay: float = 1.0
    max_delay: float = 10.0
    backoff_multiplier: float = 2.0
    jitter_mode: JitterMode = JitterMode.NONE
    jitter_fraction: float = 0.0
    jitter_source: JitterSource | None = None
    retryable_exceptions: tuple[type[BaseException], ...] = ()
    classifier: Callable[[BaseException], bool] | None = None

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0.0:
            raise ValueError("base_delay must be >= 0")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if self.backoff_multiplier < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        if not 0.0 <= self.jitter_fraction <= 1.0:
            raise ValueError("jitter_fraction must be within [0.0, 1.0]")
        if isinstance(self.retryable_exceptions, type) and issubclass(
            self.retryable_exceptions, BaseException
        ):
            object.__setattr__(
                self, "retryable_exceptions", (self.retryable_exceptions,)
            )
        if self.jitter_mode == JitterMode.BOUNDED:
            if self.jitter_source is None:
                object.__setattr__(self, "jitter_source", DefaultJitterSource())
            if not 0.0 <= self.jitter_fraction <= 1.0:
                raise ValueError("jitter_fraction must be within [0.0, 1.0]")

    def backoff(self, failed_attempt: int) -> float:
        """Raw exponential backoff for the failed attempt number (no jitter)."""
        return min(
            self.max_delay, self.base_delay * self.backoff_multiplier ** (failed_attempt - 1)
        )

    def delay_for_retry(self, failed_attempt: int) -> float:
        """Backoff delay including optional bounded jitter, capped by max_delay."""
        base = self.backoff(failed_attempt)
        if self.jitter_mode != JitterMode.BOUNDED:
            return base
        assert self.jitter_source is not None
        jitter = self.jitter_fraction * base * self.jitter_source.sample()
        return min(self.max_delay, base + jitter)

    def is_retryable(self, exc: BaseException) -> bool:
        """Classify an exception: explicit markers only, never text heuristics."""
        if isinstance(exc, RetryableError):
            return True
        if isinstance(exc, self.retryable_exceptions):
            return True
        if self.classifier is not None:
            return self.classifier(exc)
        return False
