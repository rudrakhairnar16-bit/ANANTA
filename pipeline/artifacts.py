import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
        self._index: dict[str, ArtifactMetadata] = {}
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
        index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
        episode_dir = self.base_path / episode_id
        episode_dir.mkdir(parents=True, exist_ok=True)

        existing_versions = [
            int(meta.version) for meta in self._index.values()
            if meta.episode_id == episode_id and meta.stage == stage
        ]

        version = max(existing_versions, default=0) + 1

        artifact_id = f"{episode_id}:{stage}:v{version}"
        data_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        checksum = self._compute_checksum(data_bytes)

        artifact_path = self._get_artifact_path(episode_id, stage, version)
        metadata_path = self._get_metadata_path(episode_id, stage, version)

        artifact_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

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

        metadata_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
        self._index[artifact_id] = metadata
        self._save_index()

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
        if version is None:
            versions = [
                (meta.version, artifact_id) for artifact_id, meta in self._index.items()
                if meta.stage == stage and meta.name.startswith(f"{episode_id}:")
            ]
            if not versions:
                return None
            version = max(v for v, _ in versions)

        artifact_id = f"{episode_id}:{stage}:v{version}"
        metadata = self._index.get(artifact_id)
        if not metadata:
            return None

        artifact_path = self._get_artifact_path(episode_id, stage, version)
        if not artifact_path.exists():
            return None

        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        return data, metadata

    def get_latest(
        self,
        episode_id: str,
        stage: str,
    ) -> tuple[dict[str, Any], ArtifactMetadata] | None:
        return self.get(episode_id, stage, version=None)

    def list_artifacts(self, episode_id: str) -> list[ArtifactMetadata]:
        return [
            meta for meta in self._index.values()
            if meta.name.startswith(f"{episode_id}:")
        ]

    def list_stages(self, episode_id: str) -> list[str]:
        return sorted({
            meta.stage for meta in self._index.values()
            if meta.name.startswith(f"{episode_id}:")
        })

    def delete(self, episode_id: str, stage: str, version: int):
        artifact_id = f"{episode_id}:{stage}:v{version}"
        if artifact_id in self._index:
            del self._index[artifact_id]
            self._save_index()

        artifact_path = self._get_artifact_path(episode_id, stage, version)
        metadata_path = self._get_metadata_path(episode_id, stage, version)

        if artifact_path.exists():
            artifact_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()

    def cleanup_episode(self, episode_id: str):
        for artifact_id in list(self._index.keys()):
            if artifact_id.startswith(f"{episode_id}:"):
                del self._index[artifact_id]
        self._save_index()

        episode_dir = self.base_path / episode_id
        if episode_dir.exists():
            shutil.rmtree(episode_dir)


class ArtifactManager:
    def __init__(self, artifact_store: ArtifactStore | None = None):
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
