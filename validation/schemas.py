import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.retry import RetryableError

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    jsonschema = None


@dataclass
class ValidationFeedback:
    """Structured feedback payload detailing schema validation errors for model correction."""
    stage: str
    attempt: int
    errors: list[str]
    message: str
    previous_output: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "attempt": self.attempt,
            "errors": self.errors,
            "message": self.message,
        }

    def format_prompt_instruction(self) -> str:
        errors_str = "\n".join(f"- {err}" for err in self.errors)
        return (
            "\n\n### VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT ###\n"
            f"Your previous output for stage '{self.stage}' failed schema validation:\n"
            f"{errors_str}\n\n"
            "Please fix the above errors and ensure your JSON response matches the "
            "required schema exactly."
        )


class SchemaValidationError(RetryableError, ValueError):
    """Raised when stage output fails schema validation."""

    def __init__(
        self,
        message: str,
        feedback: ValidationFeedback | None = None,
        errors: list[str] | list[Any] | None = None,
        stage: str | None = None,
    ):
        super().__init__(message)
        self.feedback = feedback
        self.errors = errors or []
        self.stage = stage


@dataclass
class ValidationError:
    path: str
    message: str
    validator: str
    instance: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "message": self.message,
            "validator": self.validator,
        }


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, path: str, message: str, validator: str = "custom", instance: Any = None):
        self.valid = False
        self.errors.append(ValidationError(path, message, validator, instance))

    def add_warning(self, message: str):
        self.warnings.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings,
        }


DEFAULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "story": {
        "type": "object",
        "required": ["episode_id", "title"],
        "properties": {
            "episode_id": {"type": "string"},
            "title": {"type": "string"},
            "logline": {"type": "string"},
            "duration_seconds": {"type": "integer"},
            "characters": {"type": "array"},
            "locations": {"type": "array"},
            "scenes": {"type": "array"},
        },
    },
    "story_output": {
        "type": "object",
        "required": ["synopsis", "themes", "acts", "beats"],
        "properties": {
            "synopsis": {"type": "string", "minLength": 1},
            "themes": {"type": "array", "items": {"type": "string"}},
            "acts": {"type": "integer", "minimum": 1},
            "beats": {"type": "array", "items": {"type": "string"}},
        },
    },
    "screenplay_output": {
        "type": "object",
        "required": ["scenes", "total_pages"],
        "properties": {
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "scene_id",
                        "location",
                        "characters",
                        "dialogue_blocks",
                        "action_lines",
                    ],
                    "properties": {
                        "scene_id": {"type": "string"},
                        "location": {"type": "string"},
                        "characters": {"type": "array", "items": {"type": "string"}},
                        "dialogue_blocks": {"type": "integer"},
                        "action_lines": {"type": "integer"},
                    },
                },
            },
            "total_pages": {"type": "integer"},
        },
    },
    "scene_plan_output": {
        "type": "object",
        "required": ["breakdown"],
        "properties": {
            "breakdown": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scene_id", "shots", "camera_setups", "vfx_notes"],
                    "properties": {
                        "scene_id": {"type": "string"},
                        "shots": {"type": "integer"},
                        "camera_setups": {"type": "integer"},
                        "vfx_notes": {"type": "string"},
                    },
                },
            },
        },
    },
    "character_output": {
        "type": "object",
        "required": ["profiles"],
        "properties": {
            "profiles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "name", "arc", "key_moments"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "arc": {"type": "string"},
                        "key_moments": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
    "world_output": {
        "type": "object",
        "required": ["rules", "technology", "society"],
        "properties": {
            "rules": {"type": "array", "items": {"type": "string"}},
            "technology": {"type": "array", "items": {"type": "string"}},
            "society": {"type": "array", "items": {"type": "string"}},
        },
    },
    "storyboard_output": {
        "type": "object",
        "required": ["panels", "key_frames", "aspect_ratio"],
        "properties": {
            "panels": {"type": "integer"},
            "key_frames": {"type": "array", "items": {"type": "string"}},
            "aspect_ratio": {"type": "string"},
        },
    },
    "director_output": {
        "type": "object",
        "required": ["vision", "shot_style", "pacing", "continuity_notes"],
        "properties": {
            "vision": {"type": "string"},
            "shot_style": {"type": "string"},
            "pacing": {"type": "string"},
            "continuity_notes": {"type": "array", "items": {"type": "string"}},
        },
    },
    "camera_output": {
        "type": "object",
        "required": ["lenses", "movement", "lighting"],
        "properties": {
            "lenses": {"type": "array", "items": {"type": "string"}},
            "movement": {"type": "array", "items": {"type": "string"}},
            "lighting": {"type": "array", "items": {"type": "string"}},
        },
    },
    "visual_output": {
        "type": "object",
        "required": ["concept_art", "vfx_breakdown", "color_palette"],
        "properties": {
            "concept_art": {"type": "array", "items": {"type": "string"}},
            "vfx_breakdown": {"type": "array", "items": {"type": "string"}},
            "color_palette": {"type": "array", "items": {"type": "string"}},
        },
    },
    "motion_output": {
        "type": "object",
        "required": ["animation_style", "key_sequences", "frame_rate"],
        "properties": {
            "animation_style": {"type": "string"},
            "key_sequences": {"type": "array", "items": {"type": "string"}},
            "frame_rate": {"type": "string"},
        },
    },
    "voice_output": {
        "type": "object",
        "required": ["casting", "direction", "recording_notes"],
        "properties": {
            "casting": {"type": "object"},
            "direction": {"type": "array", "items": {"type": "string"}},
            "recording_notes": {"type": "array", "items": {"type": "string"}},
        },
    },
    "music_output": {
        "type": "object",
        "required": ["themes", "cues", "style", "instrumentation"],
        "properties": {
            "themes": {"type": "array", "items": {"type": "string"}},
            "cues": {"type": "integer"},
            "style": {"type": "string"},
            "instrumentation": {"type": "array", "items": {"type": "string"}},
        },
    },
    "bgm_output": {
        "type": "object",
        "required": ["tracks", "ducking_points", "transitions"],
        "properties": {
            "tracks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scene", "mood", "duration"],
                    "properties": {
                        "scene": {"type": "string"},
                        "mood": {"type": "string"},
                        "duration": {"type": "integer"},
                    },
                },
            },
            "ducking_points": {"type": "array", "items": {"type": "string"}},
            "transitions": {"type": "array", "items": {"type": "string"}},
        },
    },
    "sfx_output": {
        "type": "object",
        "required": ["design", "spot_effects", "ambience"],
        "properties": {
            "design": {"type": "array", "items": {"type": "string"}},
            "spot_effects": {"type": "array", "items": {"type": "string"}},
            "ambience": {"type": "array", "items": {"type": "string"}},
        },
    },
    "lipsync_output": {
        "type": "object",
        "required": ["phoneme_maps", "viseme_schedule", "quality_checks"],
        "properties": {
            "phoneme_maps": {"type": "object"},
            "viseme_schedule": {"type": "string"},
            "quality_checks": {"type": "array", "items": {"type": "string"}},
        },
    },
    "edit_output": {
        "type": "object",
        "required": ["assembly", "pacing_notes", "transitions", "music_sync"],
        "properties": {
            "assembly": {"type": "string"},
            "pacing_notes": {"type": "array", "items": {"type": "string"}},
            "transitions": {"type": "array", "items": {"type": "string"}},
            "music_sync": {"type": "string"},
        },
    },
    "adobe_export_output": {
        "type": "object",
        "required": ["timeline_xml", "markers_csv", "media_bins", "readme"],
        "properties": {
            "timeline_xml": {"type": "string"},
            "markers_csv": {"type": "string"},
            "media_bins": {"type": "array", "items": {"type": "string"}},
            "readme": {"type": "string"},
        },
    },
    "qa_output": {
        "type": "object",
        "required": ["checks_passed", "issues", "approval"],
        "properties": {
            "checks_passed": {"type": "array", "items": {"type": "string"}},
            "issues": {"type": "array", "items": {"type": "string"}},
            "approval": {"type": "string"},
        },
    },
    "export_output": {
        "type": "object",
        "required": ["deliverables", "specs", "package"],
        "properties": {
            "deliverables": {"type": "array", "items": {"type": "string"}},
            "specs": {"type": "string"},
            "package": {"type": "string"},
        },
    },
    "generic_stage_output": {
        "type": "object",
        "required": ["episode_id", "stage", "version", "outputs", "approval_status"],
        "properties": {
            "episode_id": {"type": "string"},
            "stage": {"type": "string"},
            "version": {"type": "integer"},
            "generated_at": {"type": "string"},
            "inputs": {"type": "object"},
            "outputs": {"type": "object"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "approval_status": {
                "type": "string",
                "enum": ["pending", "approved", "rejected"],
            },
        },
    },
}


class StageValidator:
    def __init__(self, schema_dir: str | Path | None = None):
        self.schemas: dict[str, dict[str, Any]] = {}
        self.schema_dir = Path(schema_dir) if schema_dir else None
        self._load_schemas()

    def _load_schemas(self):
        for name, schema in DEFAULT_SCHEMAS.items():
            self.schemas[name] = schema

        if self.schema_dir and self.schema_dir.exists():
            for schema_file in self.schema_dir.glob("*.json"):
                try:
                    with open(schema_file, encoding="utf-8") as f:
                        schema = json.load(f)
                    self.schemas[schema_file.stem] = schema
                except Exception:
                    pass

    def validate_input(self, stage: str, data: dict[str, Any]) -> ValidationResult:
        schema_name = f"{stage}_input" if f"{stage}_input" in self.schemas else stage
        schema = self.schemas.get(schema_name, self.schemas.get("story"))
        return self._validate(data, schema, f"{stage}_input")

    def validate_output(self, stage: str, data: dict[str, Any]) -> ValidationResult:
        schema_name = f"{stage}_output"
        schema = self.schemas.get(schema_name, self.schemas.get("generic_stage_output"))

        target_data = data
        if (
            schema_name in self.schemas
            and isinstance(data, dict)
            and "outputs" in data
            and isinstance(data["outputs"], dict)
            and ("episode_id" in data or "stage" in data)
        ):
            target_data = data["outputs"]

        return self._validate(target_data, schema, f"{stage}_output")

    def _validate(
        self,
        data: dict[str, Any],
        schema: dict[str, Any],
        context: str,
    ) -> ValidationResult:
        result = ValidationResult(valid=True)

        if HAS_JSONSCHEMA and jsonschema:
            try:
                jsonschema.validate(instance=data, schema=schema)
            except jsonschema.ValidationError as e:
                result.add_error(
                    path=".".join(str(p) for p in e.path),
                    message=e.message,
                    validator=e.validator,
                    instance=e.instance,
                )
            except Exception as e:
                result.add_error(path="", message=f"Validation error: {e}", validator="jsonschema")
        else:
            result = self._basic_validate(data, schema, result, context)

        return result

    def _basic_validate(
        self,
        data: dict[str, Any],
        schema: dict[str, Any],
        result: ValidationResult,
        context: str,
        path: str = "",
    ) -> ValidationResult:
        required = schema.get("required", [])
        for required_field in required:
            if required_field not in data:
                result.add_error(
                    path=f"{path}.{required_field}" if path else required_field,
                    message=f"Required field '{required_field}' is missing",
                    validator="required",
                )

        properties = schema.get("properties", {})
        for field_name, field_schema in properties.items():
            if field_name in data:
                field_path = f"{path}.{field_name}" if path else field_name
                self._validate_field(data[field_name], field_schema, result, field_path)

        return result

    def _validate_field(
        self,
        value: Any,
        field_schema: dict[str, Any],
        result: ValidationResult,
        path: str,
    ):
        expected_type = field_schema.get("type")

        if expected_type == "string" and not isinstance(value, str):
            result.add_error(path, f"Expected string, got {type(value).__name__}", "type")
        elif expected_type == "integer" and not isinstance(value, int):
            result.add_error(path, f"Expected integer, got {type(value).__name__}", "type")
        elif expected_type == "array" and not isinstance(value, list):
            result.add_error(path, f"Expected array, got {type(value).__name__}", "type")
        elif expected_type == "object" and not isinstance(value, dict):
            result.add_error(path, f"Expected object, got {type(value).__name__}", "type")

        if expected_type == "string":
            min_len = field_schema.get("minLength")
            if min_len and isinstance(value, str) and len(value) < min_len:
                result.add_error(path, f"String length must be at least {min_len}", "minLength")

        if expected_type == "integer":
            minimum = field_schema.get("minimum")
            if minimum is not None and isinstance(value, int) and value < minimum:
                result.add_error(path, f"Value must be at least {minimum}", "minimum")

        if expected_type == "array":
            items_schema = field_schema.get("items", {})
            for i, item in enumerate(value):
                self._validate_field(item, items_schema, result, f"{path}[{i}]")

        if "enum" in field_schema and value not in field_schema["enum"]:
            result.add_error(path, f"Value must be one of {field_schema['enum']}", "enum")


def create_validator(schema_dir: str | Path | None = None) -> StageValidator:
    return StageValidator(schema_dir)
