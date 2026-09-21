import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    jsonschema = None


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


class StageValidator:
    def __init__(self, schema_dir: str | Path | None = None):
        self.schemas: dict[str, dict[str, Any]] = {}
        self.schema_dir = Path(schema_dir) if schema_dir else None
        self._load_schemas()

    def _load_schemas(self):
        default_schemas = {
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

        for name, schema in default_schemas.items():
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
        return self._validate(data, schema, f"{stage}_output")

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


DEFAULT_SCHEMAS = {
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
