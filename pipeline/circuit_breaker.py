"""M7 stage-scoped circuit breaker.

The breaker guards admission only: when a stage's circuit is OPEN, the
executor refuses to consume a worker slot for that stage. Retries of a
throttled stage stay pending (RETRYING) until the circuit opens access again,
so backpressure never burns thread-pool capacity.

Scope: one breaker per pipeline stage. Provider identity is not part of the
executor's admission path (M7 does not route providers), so the breaker keys
on the stage alone.

Contract:
  * ``record_success`` resets the consecutive-failure counter and closes.
  * ``record_retryable_failure`` increments the counter; reaching
    ``failure_threshold`` opens the circuit. A retryable-failure probe in
    HALF_OPEN triples it open again.
  * ``record_non_retryable_failure`` never increments the counter in CLOSED
    and never triggers the breaker (non-retryable failures terminate the
    stage instead). A non-retryable failure during a HALF_OPEN probe closes
    the circuit and terminates the stage.
"""

from dataclasses import dataclass
from enum import Enum
from threading import Lock

from pipeline.cancellation import Clock, MonotonicClock


class CircuitState(str, Enum):
    """Lifecycle of one stage-scoped circuit."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    """Configuration for a circuit breaker."""

    failure_threshold: int = 3
    cooldown_seconds: float = 5.0

    def __post_init__(self):
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if self.cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must be >= 0")


class CircuitBreaker:
    """Thread-safe circuit breaker for one stage scope."""

    def __init__(
        self,
        scope: str,
        breaker_policy: CircuitBreakerPolicy,
        clock: Clock | None = None,
    ):
        self._scope = scope
        self._threshold = breaker_policy.failure_threshold
        self._cooldown = breaker_policy.cooldown_seconds
        self._clock = clock or MonotonicClock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = Lock()

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        """Decide whether a request may be admitted.

        An OPEN circuit permits exactly one probe once the cooldown expires,
        transitioning to HALF_OPEN; no further requests are admitted until the
        probe resolves. Returns without consuming any worker resource.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if self._clock.now() < self._opened_at + self._cooldown:
                    return False
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                return True
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_success(self) -> None:
        """Record a success: reset counters and close the circuit."""
        with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def record_retryable_failure(self) -> None:
        """Record a retryable failure; may open (or reopen) the circuit."""
        with self._lock:
            self._probe_in_flight = False
            self._consecutive_failures += 1
            if self._state == CircuitState.HALF_OPEN or (
                self._consecutive_failures >= self._threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = self._clock.now()

    def record_non_retryable_failure(self) -> None:
        """Record a non-retryable failure: never trips the breaker in CLOSED.

        During a HALF_OPEN probe it closes the circuit (the failure is
        definitive, so no additional throttling is warranted).
        """
        with self._lock:
            self._probe_in_flight = False
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._opened_at = None


class CircuitBreakerRegistry:
    """Stage-keyed registry of circuit breakers (one breaker per scope)."""

    def __init__(self, breaker_policy: CircuitBreakerPolicy, clock: Clock | None = None):
        self._policy = breaker_policy
        self._clock = clock or MonotonicClock()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get(self, scope: str) -> CircuitBreaker:
        """Return (creating on first use) the breaker for a stage scope."""
        with self._lock:
            breaker = self._breakers.get(scope)
            if breaker is None:
                breaker = CircuitBreaker(scope, self._policy, self._clock)
                self._breakers[scope] = breaker
            return breaker

    def state(self, scope: str) -> CircuitState | None:
        """Current circuit state for a scope (None if never touched)."""
        with self._lock:
            breaker = self._breakers.get(scope)
            return breaker.state if breaker is not None else None
