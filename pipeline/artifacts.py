import hashlib
import json
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.atomic_io import atomic_write_text
from pipeline.episode_ids import validate_episode_id


class ArtifactIntegrityError(Exception):
    """Base exception for artifact integrity, corruption, or verification failures."""


class ArtifactCorruptionError(ArtifactIntegrityError):
    """Raised when an artifact payload or metadata is corrupted or fails checksum verification."""


@dataclass
class ArtifactMetadata:
    name: str
    stage: str
    version: int
    episode_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    size_bytes: int = 0
    checksum: str = ""
    content_type: str = "application/json"
    schema_version: str = "1.0"
    lineage: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "stage": self.stage,
            "version": self.version,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "content_type": self.content_type,
            "schema_version": self.schema_version,
            "lineage": self.lineage,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactMetadata":
        return cls(**data)


@dataclass
class ArtifactReference:
    artifact_id: str
    stage: str
    version: int
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "stage": self.stage,
            "version": self.version,
            "path": self.path,
        }


class ArtifactStore:
    def __init__(self, base_path: str | Path = "outputs/artifacts"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._index: dict[str, ArtifactMetadata] = {}
        with self._lock:
            self._load_index()

    def _load_index(self):
        index_path = self.base_path / "index.json"
        if index_path.exists():
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for artifact_id, meta in data.items():
                self._index[artifact_id] = ArtifactMetadata.from_dict(meta)

    def _save_index(self):
        index_path = self.base_path / "index.json"
        data = {k: v.to_dict() for k, v in self._index.items()}
        self._write_bytes_atomic(index_path, json.dumps(data, indent=2))

    def _write_bytes_atomic(self, path: Path, text: str):
        atomic_write_text(path, text)

    def _write_payload(self, path: Path, data: dict[str, Any]):
        self._write_bytes_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))

    def _write_metadata(self, path: Path, metadata: "ArtifactMetadata"):
        self._write_bytes_atomic(path, json.dumps(metadata.to_dict(), indent=2))

    def _compute_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    def _get_artifact_path(self, episode_id: str, stage: str, version: int) -> Path:
        return self.base_path / episode_id / f"{stage}_v{version}.json"

    def _get_metadata_path(self, episode_id: str, stage: str, version: int) -> Path:
        return self.base_path / episode_id / f"{stage}_v{version}.meta.json"

    def store(
        self,
        episode_id: str,
        stage: str,
        data: dict[str, Any],
        lineage: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> ArtifactReference:
        validate_episode_id(episode_id)
        episode_dir = self.base_path / episode_id
        episode_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._load_index()
            existing_versions = [
                int(meta.version)
                for meta in self._index.values()
                if meta.stage == stage and meta.name.startswith(f"{episode_id}:")
            ]

            version = max(existing_versions, default=0) + 1

            artifact_id = f"{episode_id}:{stage}:v{version}"
            data_text = json.dumps(data, indent=2, ensure_ascii=False)
            data_bytes = data_text.encode("utf-8")
            checksum = self._compute_checksum(data_bytes)

            artifact_path = self._get_artifact_path(episode_id, stage, version)
            metadata_path = self._get_metadata_path(episode_id, stage, version)

            self._write_payload(artifact_path, data)

            metadata = ArtifactMetadata(
                name=artifact_id,
                stage=stage,
                version=version,
                episode_id=episode_id,
                size_bytes=len(data_bytes),
                checksum=checksum,
                lineage=lineage or {},
                tags=tags or [],
            )

            self._write_metadata(metadata_path, metadata)
            self._index[artifact_id] = metadata
            try:
                self._save_index()
            except BaseException:
                self._index.pop(artifact_id, None)
                raise

            return ArtifactReference(
                artifact_id=artifact_id,
                stage=stage,
                version=version,
                path=str(artifact_path),
            )

    def get(
        self,
        episode_id: str,
        stage: str,
        version: int | None = None,
    ) -> tuple[dict[str, Any], ArtifactMetadata] | None:
        validate_episode_id(episode_id)
        with self._lock:
            if version is None:
                versions = [
                    (meta.version, artifact_id)
                    for artifact_id, meta in self._index.items()
                    if meta.stage == stage and meta.name.startswith(f"{episode_id}:")
                ]
                if not versions:
                    self._load_index()
                    versions = [
                        (meta.version, artifact_id)
                        for artifact_id, meta in self._index.items()
                        if meta.stage == stage and meta.name.startswith(f"{episode_id}:")
                    ]
                if not versions:
                    return None
                version = max(v for v, _ in versions)

            artifact_id = f"{episode_id}:{stage}:v{version}"
            metadata = self._index.get(artifact_id)
            if not metadata:
                self._load_index()
                metadata = self._index.get(artifact_id)
            if not metadata:
                return None

            artifact_path = self._get_artifact_path(episode_id, stage, version)
            if not artifact_path.exists():
                return None

            try:
                raw_bytes = artifact_path.read_bytes()
            except OSError as e:
                raise ArtifactCorruptionError(f"Cannot read artifact {artifact_id}: {e}") from e

            if metadata.checksum:
                computed = self._compute_checksum(raw_bytes)
                if computed != metadata.checksum:
                    raise ArtifactCorruptionError(
                        f"Checksum mismatch for artifact {artifact_id}: "
                        f"expected {metadata.checksum}, got {computed} (tampered or corrupted)"
                    )

            try:
                data = json.loads(raw_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ArtifactCorruptionError(
                    f"Malformed JSON in artifact {artifact_id}: {e}"
                ) from e

            return data, metadata

    def reconcile_artifacts(self, episode_id: str) -> list[ArtifactReference]:
        validate_episode_id(episode_id)
        episode_dir = self.base_path / episode_id
        if not episode_dir.exists():
            return []

        with self._lock:
            reconciled: list[ArtifactReference] = []
            for payload_path in sorted(episode_dir.glob("*_v*.json")):
                if payload_path.name.endswith(".meta.json"):
                    continue

                name_parts = payload_path.stem.split("_v")
                if len(name_parts) != 2:
                    continue
                stage, ver_str = name_parts
                try:
                    version = int(ver_str)
                except ValueError:
                    continue

                artifact_id = f"{episode_id}:{stage}:v{version}"
                if artifact_id in self._index:
                    continue

                meta_path = episode_dir / f"{stage}_v{version}.meta.json"
                if not meta_path.exists():
                    continue

                try:
                    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta = ArtifactMetadata.from_dict(meta_data)
                    raw_bytes = payload_path.read_bytes()
                    computed_checksum = self._compute_checksum(raw_bytes)
                    if meta.checksum and computed_checksum != meta.checksum:
                        continue
                    json.loads(raw_bytes.decode("utf-8"))
                except Exception:
                    continue

                self._index[artifact_id] = meta
                ref = ArtifactReference(
                    artifact_id=artifact_id,
                    stage=stage,
                    version=version,
                    path=str(payload_path),
                )
                reconciled.append(ref)

            if reconciled:
                self._save_index()

            return reconciled

    def verify_integrity(self, episode_id: str) -> bool:
        validate_episode_id(episode_id)
        with self._lock:
            self._load_index()
            artifacts = self.list_artifacts(episode_id)
            if not artifacts:
                return True
            for meta in artifacts:
                try:
                    res = self.get(episode_id, meta.stage, version=meta.version)
                    if res is None:
                        return False
                except Exception:
                    return False
            return True

    def get_latest(
        self,
        episode_id: str,
        stage: str,
    ) -> tuple[dict[str, Any], ArtifactMetadata] | None:
        return self.get(episode_id, stage, version=None)

    def list_artifacts(self, episode_id: str) -> list[ArtifactMetadata]:
        with self._lock:
            return [meta for meta in self._index.values() if meta.name.startswith(f"{episode_id}:")]

    def list_stages(self, episode_id: str) -> list[str]:
        with self._lock:
            return sorted(
                {
                    meta.stage
                    for meta in self._index.values()
                    if meta.name.startswith(f"{episode_id}:")
                }
            )

    def delete(self, episode_id: str, stage: str, version: int):
        validate_episode_id(episode_id)
        artifact_id = f"{episode_id}:{stage}:v{version}"
        with self._lock:
            removed = None
            if artifact_id in self._index:
                removed = self._index.pop(artifact_id)
                try:
                    self._save_index()
                except BaseException:
                    if removed is not None:
                        self._index[artifact_id] = removed
                    raise

            artifact_path = self._get_artifact_path(episode_id, stage, version)
            metadata_path = self._get_metadata_path(episode_id, stage, version)

            if artifact_path.exists():
                artifact_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()

    def cleanup_episode(self, episode_id: str):
        validate_episode_id(episode_id)
        with self._lock:
            removed: dict[str, ArtifactMetadata] = {}
            for artifact_id in list(self._index.keys()):
                if artifact_id.startswith(f"{episode_id}:"):
                    removed[artifact_id] = self._index.pop(artifact_id)
            try:
                self._save_index()
            except BaseException:
                self._index.update(removed)
                raise

            episode_dir = self.base_path / episode_id
            if episode_dir.exists():
                shutil.rmtree(episode_dir)


class ArtifactManager:
    def __init__(self, artifact_store: ArtifactStore | Path | str | None = None):
        if isinstance(artifact_store, (Path, str)):
            self.store = ArtifactStore(base_path=artifact_store)
        else:
            self.store = artifact_store or ArtifactStore()

    def store_stage_output(
        self,
        episode_id: str,
        stage: str,
        output_data: dict[str, Any],
        input_artifacts: list[ArtifactReference] | None = None,
        tags: list[str] | None = None,
    ) -> ArtifactReference:
        lineage = {
            "input_artifacts": [ref.to_dict() for ref in (input_artifacts or [])],
            "output_keys": list(output_data.get("outputs", {}).keys()),
        }
        return self.store.store(episode_id, stage, output_data, lineage=lineage, tags=tags)

    def get_stage_input(self, episode_id: str, stage: str) -> dict[str, Any] | None:
        result = self.store.get_latest(episode_id, stage)
        if result:
            return result[0]
        return None

    def get_latest_artifact(self, episode_id: str, stage: str) -> dict[str, Any] | None:
        result = self.store.get_latest(episode_id, stage)
        if result:
            return result[0]
        return None

    def verify_integrity(self, episode_id: str) -> bool:
        return self.store.verify_integrity(episode_id)

    def reconcile_artifacts(self, episode_id: str) -> list[ArtifactReference]:
        return self.store.reconcile_artifacts(episode_id)
