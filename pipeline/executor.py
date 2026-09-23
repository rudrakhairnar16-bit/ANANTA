import contextlib
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from config_v2 import get_settings
from pipeline.cancellation import (
    CancellationToken,
    Clock,
    MonotonicClock,
    StageOutcome,
)
from pipeline.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerPolicy,
    CircuitBreakerRegistry,
    CircuitState,
)
from pipeline.execution import ExecutionId
from pipeline.retry import RetryPolicy
from pipeline.scheduler import SchedulerError, StageScheduler, StageStatus
from pipeline.state import InvalidStateTransitionError

_CANCEL_TERMINAL = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.FAILED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
        StageStatus.BLOCKED,
    }
)


@dataclass(frozen=True)
class WorkerResult:
    """Immutable worker execution result."""
    stage: str
    execution_id: ExecutionId
    attempt_number: int
    success: bool
    outcome: StageOutcome = StageOutcome.SUCCESS
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0
    retryable: bool = False


@dataclass(frozen=True)
class ExecutorConfig:
    """Configuration for the pipeline executor."""
    max_workers: int = 4
    agent_factory: Callable[[str], Callable[..., dict[str, Any]]] | None = None
    episode_id: str | None = None
    timeout_seconds: float | None = None
    stage_timeouts: dict[str, float] | None = None
    clock: Clock | None = None
    retry_policy: RetryPolicy | None = None
    breaker_policy: CircuitBreakerPolicy | None = None

    @classmethod
    def from_settings(cls) -> "ExecutorConfig":
        settings = get_settings()
        return cls(max_workers=settings.pipeline.max_parallel_stages)


@dataclass
class _WorkerTask:
    """Internal representation of a worker task."""
    stage: str
    execution_id: ExecutionId
    attempt_number: int
    agent_callable: Callable[..., dict[str, Any]]
    token: CancellationToken
    future: Future | None = None
    deadline: float | None = None
    started: threading.Event = field(default_factory=threading.Event)
    started_at: float = field(default_factory=time.perf_counter)


@dataclass
class _RetryPlan:
    """Internal control-plane record scheduling one stage retry attempt."""
    attempt_number: int
    eligible_at: float
    min_admit_scan: int = 0


class PipelineExecutor:
    """
    Concurrent pipeline executor that consumes the deterministic scheduler.

    The scheduler remains the SOLE OWNER of stage lifecycle state. The
    executor owns worker execution mechanics only: admission, dispatch,
    timeout detection, cooperative cancellation, and result validation.
    M7 adds explicit retry, exponential backoff, and a stage-scoped circuit
    breaker to this control plane: a retryable failure is converted into the
    scheduler's RETRYING transition, backoff is timed by the injected clock
    (never by sleeping inside a worker), and an OPEN circuit refuses to
    consume a worker slot for the throttled stage.
    """

    def __init__(self, scheduler: StageScheduler, config: ExecutorConfig | None = None):
        self._scheduler = scheduler
        self._config = config or ExecutorConfig.from_settings()
        self._executor: ThreadPoolExecutor | None = None
        self._active_tasks: dict[str, _WorkerTask] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._results: dict[str, WorkerResult] = {}
        self._outcomes: dict[str, StageOutcome] = {}
        self._invalidated: dict[str, int] = {}
        self._pipeline_cancelled = False
        self._clock: Clock = self._config.clock or MonotonicClock()
        self._episode_id = self._config.episode_id or str(scheduler.episode_id)
        self._admission_order: list[str] = []
        self._canonical = self._compute_canonical_order()
        self._retry_policy: RetryPolicy | None = self._config.retry_policy
        self._retry_plans: dict[str, _RetryPlan] = {}
        self._retry_counts: dict[str, int] = {}
        self._scan_id: int = 0
        self._breakers: CircuitBreakerRegistry | None = (
            CircuitBreakerRegistry(self._config.breaker_policy, self._clock)
            if self._config.breaker_policy is not None
            else None
        )

    def _compute_canonical_order(self) -> list[str]:
        """Stable topological order (registration order as tie-break).

        Stages are listed so that every dependency precedes its dependents,
        with independent stages ordered by registration. The executor admits
        stages strictly in this order (never skipping an earlier PENDING
        stage), which makes the recorded admission sequence reproducible
        across runs regardless of real-time completion order.
        """
        required = self._scheduler.required_dependencies
        stages = list(self._scheduler.stage_order())
        indegree = {stage: len(required(stage)) for stage in stages}
        dependents: dict[str, list[str]] = defaultdict(list)
        for stage in stages:
            for dep in required(stage):
                dependents[dep].append(stage)
        index = {stage: i for i, stage in enumerate(stages)}
        ready = [stage for stage in stages if indegree[stage] == 0]
        ready.sort(key=index.__getitem__)
        order: list[str] = []
        while ready:
            stage = ready.pop(0)
            order.append(stage)
            for dependent in dependents[stage]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort(key=index.__getitem__)
        return order

    def run(self) -> dict[str, WorkerResult]:
        """Run the pipeline to completion or until no more work can be admitted."""
        self._executor = ThreadPoolExecutor(max_workers=self._config.max_workers)
        try:
            self._run_loop()
        finally:
            self._shutdown_executor()
        return self._results

    def _run_loop(self):
        """Main execution loop: scan timeouts, admit ready stages, collect results."""
        while not self._shutdown:
            self._scan_id += 1
            self._scan_timeouts()
            self._admit_ready_stages()
            if not self._collect_completed_workers():
                if self._scheduler.is_finished() or not self._has_pending_work():
                    break
                time.sleep(0.001)
        self._wait_for_remaining_workers()

    def _pending_blocked_by_retry(self, stage: str) -> bool:
        """True when a PENDING-not-ready stage waits on a RETRYING dependency.

        A RETRYING dependency holds no worker slot: it is admitted only once
        its time-based backoff deadline (``eligible_at`` on the injected clock)
        elapses. A not-ready PENDING stage blocked by such a dependency must
        therefore never ``break`` the canonical scan — it is skipped so that
        independent later stages keep flowing during the backoff (M7: a stage
        blocked by a retry waiting in backoff must not starve independent
        branches; and an independent stage must proceed while another is
        retry-waiting). A PENDING stage blocked by an in-flight (RUNNING /
        QUEUED) dependency still ``break``s, preserving the M6 deterministic
        admission order.
        """
        for dep in self._scheduler.required_dependencies(stage):
            if (
                self._scheduler.status(dep) == StageStatus.RETRYING
                and stage not in self._retry_plans
            ):
                return True
        return False

    def _admit_ready_stages(self):
        """Admit ready stages in deterministic canonical order and submit workers.

        Admission walks the precomputed topological order and submits every
        stage whose dependencies are satisfied, but never advances past an
        earlier stage that is still PENDING (waiting on in-flight dependencies).
        This makes the admission sequence reproducible across runs regardless
        of which parent happens to complete first. The thread pool itself
        bounds simultaneous execution to ``max_workers``; every
        submitted-but-not-started stage remains in ``QUEUED`` until its worker
        thread actually begins (see ``_promote_started_workers``).

        M7 extends the same canonical scan with retry admission: a stage in
        RETRYING is admitted once its backoff deadline (``eligible_at``) on
        the injected clock has elapsed, and an OPEN circuit refuses admission
        without consuming a worker slot. A retry-waiting stage is skipped
        (never breaks the scan), so independent later stages keep flowing.
        """
        if self._pipeline_cancelled:
            return
        with self._lock:
            self._promote_started_workers()
            now = self._clock.now()
            ready = set(self._scheduler.ready_stages())
            for stage in self._canonical:
                if stage in self._active_tasks:
                    continue
                status = self._scheduler.status(stage)
                if status == StageStatus.PENDING:
                    if stage not in ready:
                        if self._pending_blocked_by_retry(stage):
                            continue
                        break
                    self._submit_attempt(stage, now)
                elif status == StageStatus.RETRYING:
                    self._admit_retry(stage, now)

    def _submit_attempt(self, stage: str, now: float) -> bool:
        """Admit and submit one worker attempt for a stage (fresh or retried).

        Circuit admission gate: an OPEN circuit rejects the attempt before any
        worker is dispatched, so backpressure never occupies the pool. Returns
        True only when a worker was actually submitted. ``mark_queued``
        transitions PENDING -> QUEUED (fresh) or RETRYING -> QUEUED (retry) on
        the scheduler's life-cycle, keeping the scheduler the sole owner of
        status transitions.
        """
        if self._breakers is not None and not self._breakers.get(stage).allow_request():
            return False

        try:
            self._scheduler.mark_queued(stage)
        except SchedulerError:
            return False

        agent_callable = (
            self._config.agent_factory(stage)
            if self._config.agent_factory
            else None
        )
        if agent_callable is None:
            with contextlib.suppress(SchedulerError):
                self._scheduler.fail(stage, "No agent factory configured")
            self._outcomes[stage] = StageOutcome.FAILURE
            return False

        task = _WorkerTask(
            stage=stage,
            execution_id=self._scheduler.execution_id,
            attempt_number=self._scheduler.instance(stage).attempt_number,
            agent_callable=agent_callable,
            token=CancellationToken(),
            deadline=self._deadline_for(stage, now),
        )
        task.future = self._executor.submit(
            self._run_worker, stage, task.agent_callable, task.token, task.started
        )
        self._active_tasks[stage] = task
        self._admission_order.append(stage)
        return True

    def _admit_retry(self, stage: str, now: float):
        """Admit a retry plan once its backoff deadline and circuit allow it.

        The plan is removed only when the attempt is actually submitted. A
        circuit-denied retry keeps its plan so it can be admitted once the
        cooldown expires (HALF_OPEN probe), exhausting no worker slot.
        """
        plan = self._retry_plans.get(stage)
        if plan is None:
            return
        if self._scheduler.instance(stage).attempt_number != plan.attempt_number:
            self._retry_plans.pop(stage, None)
            return
        if now < plan.eligible_at:
            return
        if self._scan_id < plan.min_admit_scan:
            return
        if (
            self._retry_policy is not None
            and plan.attempt_number > self._retry_policy.max_attempts
        ):
            self._retry_plans.pop(stage, None)
            return
        if (
            self._submit_attempt(stage, now)
            or self._scheduler.status(stage) == StageStatus.FAILED
        ):
            self._retry_plans.pop(stage, None)

    def _promote_started_workers(self):
        """Transition QUEUED -> RUNNING once a worker thread has actually begun."""
        for stage, task in self._active_tasks.items():
            if not task.started.is_set():
                continue
            if self._scheduler.status(stage) != StageStatus.QUEUED:
                continue
            with contextlib.suppress(SchedulerError, InvalidStateTransitionError):
                self._scheduler.mark_running(stage)

    def _deadline_for(self, stage: str, now: float) -> float | None:
        """Resolve the per-stage deadline on the injected clock."""
        timeout: float | None = None
        if self._config.stage_timeouts:
            timeout = self._config.stage_timeouts.get(stage)
        if timeout is None:
            timeout = self._config.timeout_seconds
        if timeout is None or timeout <= 0:
            return None
        return now + timeout

    def _run_worker(
        self,
        stage: str,
        agent_callable: Callable[..., dict[str, Any]],
        token: CancellationToken,
        started_event: threading.Event,
    ) -> WorkerResult:
        """Execute a single stage worker and return immutable result."""
        started_event.set()
        started_at = time.perf_counter()
        try:
            inputs = {
                "episode_id": self._episode_id,
                "stage": stage,
                "cancellation_token": token,
            }
            result_data = agent_callable(inputs)
            duration_ms = (time.perf_counter() - started_at) * 1000
            outcome = StageOutcome.CANCELLED if token.is_cancelled() else StageOutcome.SUCCESS
            return WorkerResult(
                stage=stage,
                execution_id=self._scheduler.execution_id,
                attempt_number=self._scheduler.instance(stage).attempt_number,
                success=True,
                outcome=outcome,
                data=result_data,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - started_at) * 1000
            retryable = bool(self._retry_policy and self._retry_policy.is_retryable(e))
            return WorkerResult(
                stage=stage,
                execution_id=self._scheduler.execution_id,
                attempt_number=self._scheduler.instance(stage).attempt_number,
                success=False,
                outcome=StageOutcome.FAILURE,
                error=str(e),
                duration_ms=duration_ms,
                retryable=retryable,
            )

    def _collect_completed_workers(self) -> bool:
        """Collect completed worker results and route through scheduler."""
        collected = False
        with self._lock:
            self._promote_started_workers()
            completed_stages = [
                stage
                for stage, task in self._active_tasks.items()
                if task.future is not None and task.future.done()
            ]

        for stage in completed_stages:
            task = self._active_tasks.pop(stage)
            try:
                result = task.future.result()
            except Exception:
                result = WorkerResult(
                    stage=stage,
                    execution_id=task.execution_id,
                    attempt_number=task.attempt_number,
                    success=False,
                    outcome=StageOutcome.FAILURE,
                    error="Worker failed",
                )

            if not self._is_result_valid(stage, result):
                continue
            self._route_attempt_result(stage, result)
            collected = True
        return collected

    def _breaker_for(self, stage: str) -> CircuitBreaker | None:
        """Resolve (creating on first use) the stage-scoped breaker, if any."""
        if self._breakers is None:
            return None
        return self._breakers.get(stage)

    def _should_retry(self, stage: str, result: WorkerResult) -> bool:
        """Decide whether a failed attempt qualifies for a retry.

        Retry requires an explicit retryable classification, a configured
        retry policy, and a remaining attempt under ``max_attempts`` (which
        counts the initial attempt as 1). Timeouts and cancellations never
        reach this path because M6 keeps them out of the FAILURE lifecycle.
        """
        if not result.retryable:
            return False
        if self._retry_policy is None:
            return False
        instance = self._scheduler.instance(stage)
        return instance.attempt_number < self._retry_policy.max_attempts

    def _schedule_retry(self, stage: str, result: WorkerResult):
        """Convert a retryable failure into a scheduled RETRYING attempt.

        The old attempt is invalidated immediately so its (possibly late)
        result can never be accepted. The scheduler bumps ``attempt_number``
        and the retry plan carries a backoff deadline computed on the injected
        clock. Backoff never blocks a worker: the control loop simply skips
        the stage until ``eligible_at`` elapses.
        """
        self._retry_counts[stage] = self._retry_counts.get(stage, 0) + 1
        self._invalidated[stage] = result.attempt_number
        delay = self._retry_policy.delay_for_retry(result.attempt_number)
        with contextlib.suppress(SchedulerError):
            self._scheduler.begin_retry(stage)
        self._retry_plans[stage] = _RetryPlan(
            attempt_number=self._scheduler.instance(stage).attempt_number,
            eligible_at=self._clock.now() + delay,
            min_admit_scan=self._scan_id + 2,
        )

    def _route_attempt_result(self, stage: str, result: WorkerResult):
        """Route an accepted attempt result through scheduler and circuit.

        A success completes the stage and (if a breaker exists) records a
        success on its circuit. A retryable failure schedules a retry without
        publishing a worker result; a non-retryable (or exhausted) failure
        terminates the stage as FAILED. Only terminal attempts are stored in
        ``_results``, so stale intermediate outputs never escape.
        """
        if not self._is_result_valid(stage, result):
            return
        breaker = self._breaker_for(stage)

        if result.success:
            if breaker:
                breaker.record_success()
            try:
                self._scheduler.complete(stage)
            except SchedulerError:
                return
            self._results[stage] = result
            self._outcomes[stage] = StageOutcome.SUCCESS
            return

        if self._should_retry(stage, result):
            if breaker:
                breaker.record_retryable_failure()
            self._schedule_retry(stage, result)
            return

        if breaker:
            breaker.record_non_retryable_failure()
        try:
            self._scheduler.fail(stage, result.error or "Unknown error")
        except SchedulerError:
            return
        self._results[stage] = result
        self._outcomes[stage] = StageOutcome.FAILURE

    def _is_result_valid(self, stage: str, result: WorkerResult) -> bool:
        """Validate that the result belongs to the current execution/attempt."""
        if result.execution_id != self._scheduler.execution_id:
            return False
        if self._invalidated.get(stage) == result.attempt_number:
            return False
        instance = self._scheduler.instance(stage)
        if result.attempt_number != instance.attempt_number:
            return False
        return instance.status not in (
            StageStatus.CANCELLED,
            StageStatus.BLOCKED,
            StageStatus.SKIPPED,
        )

    def cancel_stage(self, stage: str, *, reason: str = "user_requested"):
        """Cancel one stage: queued, running, or retry-waiting workers stop."""
        with self._lock:
            instance = self._scheduler.instance(stage)
            if instance.status in _CANCEL_TERMINAL:
                raise SchedulerError(
                    f"stage '{stage}' is {instance.status.value} and cannot be cancelled"
                )
            with contextlib.suppress(SchedulerError):
                self._scheduler.cancel(stage, reason=reason)
            self._outcomes[stage] = StageOutcome.CANCELLED
            self._invalidated[stage] = instance.attempt_number
            self._retry_plans.pop(stage, None)

            task = self._active_tasks.get(stage)
            if task is not None:
                task.token.cancel(reason)
                if task.future is not None:
                    task.future.cancel()
                del self._active_tasks[stage]

    def request_pipeline_cancellation(self, *, reason: str = "user_requested"):
        """Cancel the whole pipeline: no new admissions, cooperative shutdown."""
        with self._lock:
            self._pipeline_cancelled = True
            for stage in self._scheduler.stage_order():
                instance = self._scheduler.instance(stage)
                if instance.status in (
                    StageStatus.PENDING,
                    StageStatus.QUEUED,
                    StageStatus.RUNNING,
                    StageStatus.RETRYING,
                ):
                    with contextlib.suppress(SchedulerError):
                        self._scheduler.cancel(stage, reason=reason)
                    self._outcomes[stage] = StageOutcome.CANCELLED
                    self._invalidated[stage] = instance.attempt_number
            self._retry_plans.clear()

            for stage, task in list(self._active_tasks.items()):
                task.token.cancel(reason)
                if task.future is not None:
                    task.future.cancel()
                del self._active_tasks[stage]

    def retry_counts(self) -> dict[str, int]:
        """Snapshot of scheduled retries per stage."""
        return dict(self._retry_counts)

    def circuit_state(self, stage: str) -> CircuitState | None:
        """Current circuit state for a stage (None when no breaker configured)."""
        if self._breakers is None:
            return None
        return self._breakers.state(stage)

    def outcomes(self) -> dict[str, StageOutcome]:
        """Snapshot of structured per-stage execution outcomes."""
        return dict(self._outcomes)

    def pipeline_cancelled(self) -> bool:
        return self._pipeline_cancelled

    def _has_pending_work(self) -> bool:
        """Check if there is work the control loop should stay alive for.

        In addition to in-flight workers and PENDING stages, any scheduled
        retry plan (a stage sleeping out its backoff or waiting on a circuit)
        keeps the loop running so the retry can later be admitted.
        """
        with self._lock:
            if self._active_tasks:
                return True
        if self._retry_plans:
            return True
        return any(
            self._scheduler.status(stage) == StageStatus.PENDING
            for stage in self._scheduler.stage_order()
        )

    def _scan_timeouts(self):
        """Detect deadline violations on the control path (deterministic)."""
        if self._config.timeout_seconds is None and not self._config.stage_timeouts:
            return
        with self._lock:
            now = self._clock.now()
            for stage, task in list(self._active_tasks.items()):
                if task.deadline is not None and now >= task.deadline:
                    self._handle_timeout(stage, task)

    def _handle_timeout(self, stage: str, task: _WorkerTask):
        """Cancel an expired stage; its attempt becomes permanently stale."""
        if task.future is not None and task.future.done():
            return
        instance = self._scheduler.instance(stage)
        if instance.status not in (StageStatus.QUEUED, StageStatus.RUNNING):
            return
        with contextlib.suppress(SchedulerError):
            self._scheduler.cancel(stage, reason="timeout")
        self._outcomes[stage] = StageOutcome.TIMEOUT
        self._invalidated[stage] = task.attempt_number
        task.token.cancel("timeout")
        if task.future is not None:
            task.future.cancel()
        self._active_tasks.pop(stage, None)

    def _wait_for_remaining_workers(self):
        """Wait for any remaining active workers to complete."""
        with self._lock:
            self._promote_started_workers()
            tasks = list(self._active_tasks.values())
        for task in tasks:
            stage = task.stage
            if task.future is None:
                continue
            try:
                result = task.future.result()
            except Exception:
                result = WorkerResult(
                    stage=stage,
                    execution_id=task.execution_id,
                    attempt_number=task.attempt_number,
                    success=False,
                    outcome=StageOutcome.FAILURE,
                    error="Worker failed",
                )
            self._active_tasks.pop(stage, None)
            if not self._is_result_valid(stage, result):
                continue
            self._route_attempt_result(stage, result)

    def _shutdown_executor(self):
        """Shutdown the thread pool cleanly."""
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        self._shutdown = True

    def is_finished(self) -> bool:
        """Check if execution is finished."""
        return self._scheduler.is_finished()

    def get_scheduler(self) -> StageScheduler:
        """Get the scheduler (read-only access)."""
        return self._scheduler

    def active_worker_count(self) -> int:
        """Get current active worker count."""
        with self._lock:
            return sum(
                1
                for task in self._active_tasks.values()
                if task.future is not None and not task.future.done()
            )

    def admission_order(self) -> tuple[str, ...]:
        """Get the deterministic admission order (stages submitted to workers)."""
        return tuple(self._admission_order)
