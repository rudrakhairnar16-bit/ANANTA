from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from pipeline.dependencies import get_default_dependency_graph
from pipeline.execution import (
    EpisodeId,
    ExecutionId,
    StageId,
    StageInstance,
    new_execution_id,
)
from pipeline.state import StageStatus

_TERMINAL = frozenset(
    {
        StageStatus.COMPLETED,
        StageStatus.FAILED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
        StageStatus.BLOCKED,
    }
)


class SchedulerError(ValueError):
    """Raised for scheduler-level violations (admission, readiness, registration)."""


def _normalize_edges(
    stages: tuple[str, ...],
    dependencies: Mapping[str, Sequence[str]] | None,
    optional_dependencies: Mapping[str, Sequence[str]] | None,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    declared = {
        stage: tuple(sorted(set(dependencies.get(stage, ())))) for stage in stages
    }
    optional = {
        stage: tuple(sorted(set((optional_dependencies or {}).get(stage, ()))))
        for stage in stages
    }
    known = set(stages)
    for stage in stages:
        for dep in declared[stage] + optional[stage]:
            if dep not in known:
                raise SchedulerError(
                    f"stage '{stage}' references unknown dependency '{dep}'"
                )
    required = {
        stage: tuple(dep for dep in declared[stage] if dep not in set(optional[stage]))
        for stage in stages
    }
    optional_only = {
        stage: tuple(dep for dep in declared[stage] if dep in set(optional[stage]))
        for stage in stages
    }
    return required, optional_only


@dataclass(frozen=True)
class SchedulerSnapshot:
    stage_order: tuple[str, ...]
    ready: tuple[str, ...]
    queued: tuple[str, ...]
    running: tuple[str, ...]
    completed: tuple[str, ...]
    failed: tuple[str, ...]
    skipped: tuple[str, ...]
    blocked: tuple[str, ...]
    cancelled: tuple[str, ...]
    pending: tuple[str, ...]
    finished: bool


class StageScheduler:
    """Deterministic scheduler core.

    The scheduler is the sole owner of stage lifecycle state. It stores only
    frozen ``StageInstance`` values and publishes updated values instead of
    exposing mutable shared state. All derived collections are produced by
    scanning the explicit registration order.
    """

    def __init__(
        self,
        stages: Sequence[str],
        dependencies: Mapping[str, Sequence[str]] | None = None,
        *,
        episode_id: str | EpisodeId | None = None,
        execution_id: ExecutionId | None = None,
        optional_dependencies: Mapping[str, Sequence[str]] | None = None,
    ):
        order = tuple(stages)
        if len(set(order)) != len(order):
            raise SchedulerError("stage order must not contain duplicates")
        for name in order:
            StageId(name)
        if not order:
            raise SchedulerError("stage order must not be empty")
        self._execution_id = execution_id or new_execution_id()
        if isinstance(episode_id, EpisodeId):
            self._episode_id = episode_id
        else:
            self._episode_id = EpisodeId(episode_id or "DEFAULT")

        self._order = order
        self._required, self._optional = _normalize_edges(
            order, dependencies or {}, optional_dependencies
        )

        dependents: dict[str, list[str]] = defaultdict(list)
        for stage in order:
            for dep in self._required[stage]:
                dependents[dep].append(stage)
        self._dependents = {name: tuple(children) for name, children in dependents.items()}

        self._instances: dict[str, StageInstance] = {}
        for stage in order:
            self._instances[stage] = StageInstance(
                stage=StageId(stage),
                episode_id=self._episode_id,
                execution_id=self._execution_id,
                dependencies=self._required[stage],
            )

    @property
    def execution_id(self) -> ExecutionId:
        return self._execution_id

    @property
    def episode_id(self) -> EpisodeId:
        return self._episode_id

    def stage_order(self) -> tuple[str, ...]:
        return self._order

    def required_dependencies(self, stage: str) -> tuple[str, ...]:
        return self._required.get(stage, ())

    def optional_dependencies(self, stage: str) -> tuple[str, ...]:
        return self._optional.get(stage, ())

    def _dependencies_satisfied(self, stage: str) -> bool:
        return all(
            self._instances[dep].status == StageStatus.COMPLETED
            for dep in self._required[stage]
        )

    def _lookup(self, stage: str) -> StageInstance:
        try:
            return self._instances[stage]
        except KeyError:
            raise SchedulerError(f"unknown stage '{stage}'") from None

    def status(self, stage: str) -> StageStatus:
        return self._lookup(stage).status

    def instance(self, stage: str) -> StageInstance:
        return self._lookup(stage)

    def instances(self) -> tuple[StageInstance, ...]:
        return tuple(self._instances[stage] for stage in self._order)

    def _stages_with(self, status: StageStatus) -> tuple[str, ...]:
        return tuple(
            stage
            for stage in self._order
            if self._instances[stage].status == status
        )

    def ready_stages(self) -> tuple[str, ...]:
        return tuple(
            stage
            for stage in self._order
            if self._instances[stage].status == StageStatus.PENDING
            and self._dependencies_satisfied(stage)
        )

    def queued_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.QUEUED)

    def running_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.RUNNING)

    def completed_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.COMPLETED)

    def failed_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.FAILED)

    def skipped_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.SKIPPED)

    def blocked_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.BLOCKED)

    def cancelled_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.CANCELLED)

    def pending_stages(self) -> tuple[str, ...]:
        return self._stages_with(StageStatus.PENDING)

    def blocked_downstream(self, stage: str) -> tuple[str, ...]:
        result: list[str] = []
        visited: set[str] = set()
        queue = [stage]
        index = 0
        while index < len(queue):
            current = queue[index]
            index += 1
            if current in visited:
                continue
            visited.add(current)
            for dependent in self._dependents.get(current, ()):
                if self._instances[dependent].status == StageStatus.BLOCKED:
                    result.append(dependent)
                queue.append(dependent)
        return tuple(result)

    def is_finished(self) -> bool:
        return all(
            self._instances[stage].status in _TERMINAL for stage in self._order
        )

    def snapshot(self) -> SchedulerSnapshot:
        return SchedulerSnapshot(
            stage_order=self._order,
            ready=self.ready_stages(),
            queued=self.queued_stages(),
            running=self.running_stages(),
            completed=self.completed_stages(),
            failed=self.failed_stages(),
            skipped=self.skipped_stages(),
            blocked=self.blocked_stages(),
            cancelled=self.cancelled_stages(),
            pending=self.pending_stages(),
            finished=self.is_finished(),
        )

    def _apply(self, stage: str, status: StageStatus, *, error: str | None = None):
        inst = self._lookup(stage)
        updated = inst.with_status(status, error=error)
        self._instances[stage] = updated
        if status in (
            StageStatus.FAILED,
            StageStatus.SKIPPED,
            StageStatus.CANCELLED,
            StageStatus.BLOCKED,
        ):
            self._cascade_block(stage)
        return updated

    def mark_queued(self, stage: str) -> StageInstance:
        inst = self._lookup(stage)
        if inst.status == StageStatus.RETRYING:
            self._instances[stage] = inst.with_status(StageStatus.QUEUED)
            return self._instances[stage]
        if inst.status != StageStatus.PENDING:
            raise SchedulerError(f"stage '{stage}' is not pending and cannot be queued")
        if not self._dependencies_satisfied(stage):
            raise SchedulerError(
                f"stage '{stage}' is not ready: required dependencies are not all completed"
            )
        self._instances[stage] = inst.with_status(StageStatus.QUEUED)
        return self._instances[stage]

    def begin_retry(self, stage: str) -> StageInstance:
        """Bump a running stage into RETRYING and advance the attempt number.

        The scheduler remains the sole lifecycle owner: the executor converts
        a retryable failure into an explicit RETRYING transition with
        ``attempt_number`` incremented, so a new worker runs under the next
        attempt identity. Dependency readiness is untouched (the stage was
        already runnable).
        """
        inst = self._lookup(stage)
        if inst.status != StageStatus.RUNNING:
            raise SchedulerError(f"stage '{stage}' is not running and cannot retry")
        updated = replace(
            inst,
            status=StageStatus.RETRYING,
            attempt_number=inst.attempt_number + 1,
        )
        self._instances[stage] = updated
        return updated

    def mark_running(self, stage: str) -> StageInstance:
        updated = self._lookup(stage).with_status(StageStatus.RUNNING)
        self._instances[stage] = updated
        return updated

    def complete(self, stage: str) -> StageInstance:
        inst = self._lookup(stage)
        if inst.status == StageStatus.PENDING and not self._dependencies_satisfied(stage):
            raise SchedulerError(
                f"stage '{stage}' is not ready: required dependencies are not all completed"
            )
        self._instances[stage] = inst.with_status(StageStatus.COMPLETED)
        return self._instances[stage]

    def fail(self, stage: str, error: str = "") -> StageInstance:
        return self._apply(stage, StageStatus.FAILED, error=error)

    def skip(self, stage: str) -> StageInstance:
        return self._apply(stage, StageStatus.SKIPPED)

    def cancel(self, stage: str, *, reason: str | None = None) -> StageInstance:
        return self._apply(stage, StageStatus.CANCELLED, error=reason)

    def block_stage(self, stage: str) -> StageInstance:
        return self._apply(stage, StageStatus.BLOCKED)

    def _cascade_block(self, source: str):
        queue = [source]
        index = 0
        while index < len(queue):
            current = queue[index]
            index += 1
            for dependent in self._dependents.get(current, ()):
                inst = self._instances[dependent]
                if inst.status in (StageStatus.PENDING, StageStatus.QUEUED):
                    self._instances[dependent] = inst.with_status(StageStatus.BLOCKED)
                    queue.append(dependent)


def create_ananta_scheduler(
    *,
    episode_id: str | EpisodeId | None = None,
    execution_id: ExecutionId | None = None,
) -> StageScheduler:
    graph = get_default_dependency_graph()
    order = tuple(graph.get_execution_order())
    dependencies = {
        stage: tuple(graph.get_dependencies(stage)) for stage in order
    }
    return StageScheduler(
        order,
        dependencies,
        episode_id=episode_id,
        execution_id=execution_id,
    )
