import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pipeline.atomic_io import atomic_write_text
from pipeline.episode_ids import validate_episode_id


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    QUEUED = "queued"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class InvalidStateTransitionError(ValueError):
    """Raised when a stage status transition is not in VALID_TRANSITIONS."""


class StatePersistenceError(Exception):
    """Base exception for state persistence and recovery failures."""


class StateCorruptionError(StatePersistenceError):
    """Raised when persisted pipeline state is corrupted or unparseable."""


class StateVersionError(StatePersistenceError):
    """Raised when persisted pipeline state has an unsupported schema version."""


CURRENT_SCHEMA_VERSION = "2.0"


VALID_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.PENDING: frozenset(
        {
            StageStatus.QUEUED,
            StageStatus.BLOCKED,
            StageStatus.RUNNING,
            StageStatus.RETRYING,
            StageStatus.COMPLETED,
            StageStatus.FAILED,
            StageStatus.SKIPPED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.QUEUED: frozenset(
        {
            StageStatus.RUNNING,
            StageStatus.BLOCKED,
            StageStatus.SKIPPED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.BLOCKED: frozenset(
        {
            StageStatus.QUEUED,
            StageStatus.SKIPPED,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.RUNNING: frozenset(
        {
            StageStatus.COMPLETED,
            StageStatus.FAILED,
            StageStatus.RETRYING,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.RETRYING: frozenset(
        {
            StageStatus.RUNNING,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
            StageStatus.QUEUED,
            StageStatus.RETRYING,
        }
    ),
    StageStatus.COMPLETED: frozenset(),
    StageStatus.FAILED: frozenset(),
    StageStatus.SKIPPED: frozenset(),
    StageStatus.CANCELLED: frozenset(),
}


@dataclass
class StageState:
    stage: str
    status: StageStatus = StageStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    retry_count: int = 0
    output_path: str | None = None
    metrics: dict[str, Any] | None = None

    def transition(self, new_status: StageStatus):
        if not isinstance(new_status, StageStatus):
            raise InvalidStateTransitionError(
                f"{new_status!r} is not a valid stage status"
            )
        allowed = VALID_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                "Illegal stage transition for stage "
                f"'{self.stage}': '{self.status.value}' -> '{new_status.value}'"
            )
        self.status = new_status

    def mark_running(self):
        self.transition(StageStatus.RUNNING)
        self.started_at = datetime.now(timezone.utc).isoformat()

    def mark_completed(self, output_path: str | None = None, metrics: dict[str, Any] | None = None):
        self.transition(StageStatus.COMPLETED)
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.output_path = output_path
        self.metrics = metrics

    def mark_failed(self, error: str):
        self.transition(StageStatus.FAILED)
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.error = error

    def mark_skipped(self):
        self.transition(StageStatus.SKIPPED)
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def mark_retrying(self):
        self.transition(StageStatus.RETRYING)
        self.retry_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "retry_count": self.retry_count,
            "output_path": self.output_path,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageState":
        state = cls(
            stage=data["stage"],
            status=StageStatus(data["status"]),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            retry_count=data.get("retry_count", 0),
            output_path=data.get("output_path"),
            metrics=data.get("metrics"),
        )
        return state


@dataclass
class PipelineState:
    episode_id: str
    title: str | None = None
    status: str = "pending"
    schema_version: str = CURRENT_SCHEMA_VERSION
    execution_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    stages: dict[str, StageState] = field(default_factory=dict)
    current_stage: str | None = None
    total_stages: int = 0
    completed_stages: int = 0
    failed_stages: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.stages:
            self.stages = {}

    def add_stage(self, stage: str):
        if stage not in self.stages:
            self.stages[stage] = StageState(stage=stage)
            self.total_stages += 1

    def get_stage(self, stage: str) -> StageState | None:
        return self.stages.get(stage)

    def update_stage(self, stage_state: StageState):
        self.stages[stage_state.stage] = stage_state
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self._recalculate_counts()

    def _recalculate_counts(self):
        self.completed_stages = sum(
            1 for s in self.stages.values() if s.status == StageStatus.COMPLETED
        )
        self.failed_stages = sum(
            1 for s in self.stages.values() if s.status == StageStatus.FAILED
        )

    def is_completed(self) -> bool:
        return all(
            s.status in (StageStatus.COMPLETED, StageStatus.SKIPPED)
            for s in self.stages.values()
        )

    def is_failed(self) -> bool:
        return any(s.status == StageStatus.FAILED for s in self.stages.values())

    def get_next_pending_stage(
        self, stage_order: list[str], allow_failed: bool = False
    ) -> str | None:
        runnable_statuses = {
            StageStatus.PENDING,
            StageStatus.RUNNING,
            StageStatus.RETRYING,
            StageStatus.QUEUED,
        }
        if allow_failed:
            runnable_statuses.add(StageStatus.FAILED)
        for stage in stage_order:
            state = self.stages.get(stage)
            if state and state.status in runnable_statuses:
                return stage
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "episode_id": self.episode_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "current_stage": self.current_stage,
            "total_stages": self.total_stages,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineState":
        if not isinstance(data, dict):
            raise StateCorruptionError(
                f"Expected dict for PipelineState, got {type(data).__name__}"
            )
        if "episode_id" not in data or not data["episode_id"]:
            raise StateCorruptionError("Missing required field 'episode_id' in PipelineState")

        schema_version = str(data.get("schema_version", "1.0"))
        try:
            ver_float = float(schema_version)
            if ver_float > float(CURRENT_SCHEMA_VERSION):
                raise StateVersionError(
                    f"Unsupported schema_version: {schema_version} "
                    f"(supported <= {CURRENT_SCHEMA_VERSION})"
                )
        except ValueError as e:
            raise StateVersionError(f"Invalid schema_version: {schema_version}") from e

        state = cls(
            episode_id=data["episode_id"],
            title=data.get("title"),
            status=data.get("status", "pending"),
            schema_version=schema_version,
            execution_id=data.get("execution_id"),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            completed_at=data.get("completed_at"),
            current_stage=data.get("current_stage"),
            total_stages=data.get("total_stages", 0),
            completed_stages=data.get("completed_stages", 0),
            failed_stages=data.get("failed_stages", 0),
            metadata=data.get("metadata", {}),
        )
        state.stages = {
            k: StageState.from_dict(v) for k, v in data.get("stages", {}).items()
        }
        return state


class StateStore:
    def __init__(self, base_path: str | Path = "outputs/state"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_state_path(self, episode_id: str) -> Path:
        return self.base_path / f"{episode_id}_state.json"

    def _get_backup_path(self, episode_id: str) -> Path:
        return self.base_path / f"{episode_id}_state.json.bak"

    def save(self, state: PipelineState):
        validate_episode_id(state.episode_id)
        path = self._get_state_path(state.episode_id)
        backup_path = self._get_backup_path(state.episode_id)

        # Back up existing file if present and valid
        if path.exists():
            try:
                raw = path.read_text(encoding="utf-8")
                json.loads(raw)
                atomic_write_text(backup_path, raw)
            except Exception:
                pass

        atomic_write_text(path, json.dumps(state.to_dict(), indent=2))

    def load(self, episode_id: str) -> PipelineState | None:
        validate_episode_id(episode_id)
        path = self._get_state_path(episode_id)
        backup_path = self._get_backup_path(episode_id)

        if not path.exists():
            if backup_path.exists():
                return self._load_file(backup_path, episode_id)
            return None

        try:
            return self._load_file(path, episode_id)
        except StateCorruptionError:
            if backup_path.exists():
                try:
                    return self._load_file(backup_path, episode_id)
                except Exception:
                    pass
            raise

    def _load_file(self, path: Path, episode_id: str) -> PipelineState:
        try:
            raw_text = path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise StateCorruptionError(f"Corrupted state JSON in {path.name}: {e}") from e
        except OSError as e:
            raise StateCorruptionError(f"Cannot read state file {path.name}: {e}") from e

        try:
            return PipelineState.from_dict(data)
        except (StateVersionError, StateCorruptionError):
            raise
        except Exception as e:
            raise StateCorruptionError(f"Invalid state data in {path.name}: {e}") from e

    def delete(self, episode_id: str):
        validate_episode_id(episode_id)
        path = self._get_state_path(episode_id)
        if path.exists():
            path.unlink()
        backup_path = self._get_backup_path(episode_id)
        if backup_path.exists():
            backup_path.unlink()

    def list_states(self) -> list[str]:
        return [f.stem.replace("_state", "") for f in self.base_path.glob("*_state.json")]


class CheckpointManager:
    def __init__(self, state_store: StateStore | None = None):
        self.state_store = state_store or StateStore()

    def checkpoint(self, state: PipelineState):
        self.state_store.save(state)

    def restore(self, episode_id: str) -> PipelineState | None:
        return self.state_store.load(episode_id)

    def can_resume(self, episode_id: str, allow_failed: bool = False) -> bool:
        state = self.state_store.load(episode_id)
        if not state:
            return False
        if allow_failed:
            return not state.is_completed()
        return not state.is_completed() and not state.is_failed()

    def get_resume_stage(
        self, episode_id: str, stage_order: list[str], allow_failed: bool = False
    ) -> str | None:
        state = self.state_store.load(episode_id)
        if not state:
            return None
        return state.get_next_pending_stage(stage_order, allow_failed=allow_failed)


def create_initial_state(episode_id: str, title: str, stages: list[str]) -> PipelineState:
    state = PipelineState(episode_id=episode_id, title=title, total_stages=0)
    for stage in stages:
        state.add_stage(stage)
    return state
