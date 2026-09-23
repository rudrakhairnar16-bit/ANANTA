import re
import uuid
from dataclasses import dataclass, field, replace

from pipeline.episode_ids import validate_episode_id
from pipeline.state import VALID_TRANSITIONS, InvalidStateTransitionError, StageStatus

IDENTIFIER_MAX_LENGTH = 100
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_EXECUTION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class InvalidIdentifierError(ValueError):
    """Raised when a pipeline or stage identifier is not a stable token."""


class InvalidExecutionIdError(ValueError):
    """Raised when an execution id is not a full stable run identifier."""


class InvalidAttemptNumberError(ValueError):
    """Raised when a stage attempt number is not a positive integer."""


def validate_identifier(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise InvalidIdentifierError(
            f"{label} must be a string, got {type(value).__name__}"
        )
    if not value:
        raise InvalidIdentifierError(f"{label} must not be empty")
    if len(value) > IDENTIFIER_MAX_LENGTH:
        raise InvalidIdentifierError(
            f"{label} must be at most {IDENTIFIER_MAX_LENGTH} characters"
        )
    if value in (".", ".."):
        raise InvalidIdentifierError(f"{label} must not be '.' or '..'")
    if value.startswith("."):
        raise InvalidIdentifierError(f"{label} must not start with '.'")
    if not _IDENTIFIER_RE.match(value):
        raise InvalidIdentifierError(
            f"{label} may only contain ASCII letters, digits, '_', '-' and '.'"
        )
    return value


def validate_execution_id(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidExecutionIdError(
            f"execution id must be a string, got {type(value).__name__}"
        )
    if not _EXECUTION_ID_RE.match(value):
        raise InvalidExecutionIdError(
            "execution id must be a full 32-character lowercase hex run id"
        )
    return value


def validate_attempt_number(attempt_number: int) -> int:
    if isinstance(attempt_number, bool) or not isinstance(attempt_number, int):
        raise InvalidAttemptNumberError(
            f"attempt_number must be an integer, got {type(attempt_number).__name__}"
        )
    if attempt_number < 1:
        raise InvalidAttemptNumberError("attempt_number must be >= 1")
    return attempt_number


@dataclass(frozen=True)
class PipelineId:
    name: str

    def __post_init__(self):
        validate_identifier(self.name, "pipeline id")

    def __str__(self) -> str:
        return self.name

    def to_dict(self) -> dict[str, str]:
        return {"pipeline_id": self.name}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "PipelineId":
        return cls(data["pipeline_id"])


@dataclass(frozen=True)
class ExecutionId:
    value: str

    def __post_init__(self):
        validate_execution_id(self.value)

    def __str__(self) -> str:
        return self.value

    def to_dict(self) -> dict[str, str]:
        return {"execution_id": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "ExecutionId":
        return cls(data["execution_id"])


def new_execution_id() -> ExecutionId:
    return ExecutionId(uuid.uuid4().hex)


@dataclass(frozen=True)
class EpisodeId:
    value: str

    def __post_init__(self):
        validate_episode_id(self.value)

    def __str__(self) -> str:
        return self.value

    def to_dict(self) -> dict[str, str]:
        return {"episode_id": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "EpisodeId":
        return cls(data["episode_id"])


@dataclass(frozen=True)
class StageId:
    value: str

    def __post_init__(self):
        validate_identifier(self.value, "stage id")

    def __str__(self) -> str:
        return self.value

    def to_dict(self) -> dict[str, str]:
        return {"stage_id": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "StageId":
        return cls(data["stage_id"])


@dataclass(frozen=True)
class StageAttemptId:
    execution_id: ExecutionId
    stage: StageId
    attempt_number: int

    def __post_init__(self):
        validate_attempt_number(self.attempt_number)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "execution_id": str(self.execution_id),
            "stage": str(self.stage),
            "attempt_number": self.attempt_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "StageAttemptId":
        return cls(
            execution_id=ExecutionId(data["execution_id"]),
            stage=StageId(data["stage"]),
            attempt_number=data["attempt_number"],
        )


@dataclass(frozen=True)
class StageInstance:
    stage: StageId
    episode_id: EpisodeId
    execution_id: ExecutionId
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    attempt_number: int = 1
    status: StageStatus = StageStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "dependencies", tuple(sorted(self.dependencies)))
        for dependency in self.dependencies:
            validate_identifier(dependency, "stage dependency")
        validate_attempt_number(self.attempt_number)
        if isinstance(self.status, str):
            object.__setattr__(self, "status", StageStatus(self.status))

    @property
    def attempt_id(self) -> StageAttemptId:
        return StageAttemptId(self.execution_id, self.stage, self.attempt_number)

    def with_status(
        self, new_status: StageStatus, *, error: str | None = None
    ) -> "StageInstance":
        status = StageStatus(new_status) if isinstance(new_status, str) else new_status
        if status not in VALID_TRANSITIONS.get(self.status, frozenset()):
            raise InvalidStateTransitionError(
                "Illegal stage transition for stage "
                f"'{self.stage}': '{self.status.value}' -> '{status.value}'"
            )
        if error is None:
            return replace(self, status=status)
        return replace(self, status=status, error=error)

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": str(self.stage),
            "episode_id": str(self.episode_id),
            "execution_id": str(self.execution_id),
            "dependencies": list(self.dependencies),
            "attempt_number": self.attempt_number,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "StageInstance":
        return cls(
            stage=StageId(data["stage"]),
            episode_id=EpisodeId(data["episode_id"]),
            execution_id=ExecutionId(data["execution_id"]),
            dependencies=tuple(data.get("dependencies") or ()),
            attempt_number=data.get("attempt_number", 1),
            status=StageStatus(data.get("status", "pending")),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            timeout_seconds=data.get("timeout_seconds"),
        )
