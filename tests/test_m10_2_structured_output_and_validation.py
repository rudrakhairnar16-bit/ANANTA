import json
from pathlib import Path
from typing import Any

import pytest

from agents.base_agent_v2 import BaseAgentV2
from pipeline.artifacts import ArtifactManager
from pipeline.state import PipelineState
from providers.base_v2 import (
    BaseProviderV2,
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
    ProviderResponse,
    ProviderValidationError,
)
from validation.schemas import DEFAULT_SCHEMAS, StageValidator

STAGES = [
    "story",
    "screenplay",
    "scene_plan",
    "character",
    "world",
    "storyboard",
    "director",
    "camera",
    "visual",
    "motion",
    "voice",
    "music",
    "bgm",
    "sfx",
    "lipsync",
    "edit",
    "adobe_export",
    "qa",
    "export",
]


class InvalidSchemaProvider(BaseProviderV2):
    def __init__(self, stage: str, invalid_data: dict[str, Any]):
        super().__init__(ProviderConfig(name=f"InvalidProvider_{stage}"))
        self.stage = stage
        self.invalid_data = invalid_data

    @property
    def provider_type(self) -> str:
        return "invalid"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        return ProviderResponse.success_response(
            data={"outputs": self.invalid_data},
            provider_name=self.config.name,
            metrics=self.metrics,
        )


# =========================================================================
# 1. Schema Coverage (All 19 Stages)
# =========================================================================


def test_all_19_stage_schemas_defined():
    validator = StageValidator()
    for stage in STAGES:
        schema_name = f"{stage}_output"
        assert schema_name in validator.schemas, f"Missing '{schema_name}' in StageValidator"
        assert schema_name in DEFAULT_SCHEMAS, f"Missing '{schema_name}' in DEFAULT_SCHEMAS"


def test_all_19_stage_valid_outputs_pass_validation():
    validator = StageValidator()
    mock_provider = MockProviderV2("story")
    stage_outputs = mock_provider._get_stage_outputs()

    for stage in STAGES:
        assert stage in stage_outputs, f"Missing mock output for stage '{stage}'"
        output_data = stage_outputs[stage]
        result = validator.validate_output(stage, output_data)
        assert result.valid is True, f"Output failed validation for '{stage}': {result.errors}"


def test_all_19_stage_schemas_reject_missing_required_fields():
    validator = StageValidator()
    for stage in STAGES:
        empty_data: dict[str, Any] = {}
        result = validator.validate_output(stage, empty_data)
        assert result.valid is False, f"Stage '{stage}' should reject empty output"
        assert len(result.errors) > 0, f"Stage '{stage}' should report validation errors"


def test_all_19_stage_schemas_reject_incorrect_types():
    validator = StageValidator()
    mock_provider = MockProviderV2("story")
    stage_outputs = mock_provider._get_stage_outputs()

    for stage in STAGES:
        valid_output = stage_outputs[stage]
        # Corrupt the first field by changing its type to an incompatible type
        corrupted_output = dict(valid_output)
        first_key = next(iter(corrupted_output.keys()))
        original_val = corrupted_output[first_key]
        if isinstance(original_val, (list, dict)):
            corrupted_output[first_key] = 12345
        elif isinstance(original_val, int):
            corrupted_output[first_key] = "not_an_int"
        else:
            corrupted_output[first_key] = ["not_a_string_or_primitive"]

        result = validator.validate_output(stage, corrupted_output)
        assert result.valid is False, f"Stage '{stage}' should reject bad type for '{first_key}'"


# =========================================================================
# 2. Structured JSON Parsing
# =========================================================================


def test_parse_valid_json_response():
    provider = OllamaProviderV2(stage="story")
    raw_response = {
        "response": json.dumps({
            "synopsis": "A test synopsis",
            "themes": ["ai", "future"],
            "acts": 3,
            "beats": ["b1", "b2"],
        })
    }
    parsed = provider._parse_response(raw_response, {"episode_id": "EP100", "stage": "story"})
    assert parsed["outputs"]["synopsis"] == "A test synopsis"
    assert parsed["outputs"]["acts"] == 3


def test_parse_markdown_wrapped_json_response():
    provider = OllamaProviderV2(stage="screenplay")
    payload = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "location": "Lab",
                "characters": ["Maya"],
                "dialogue_blocks": 5,
                "action_lines": 3,
            }
        ],
        "total_pages": 10,
    }
    dumped = json.dumps(payload)
    raw_response = {
        "response": f"Here is your JSON output:\n```json\n{dumped}\n```\nHope you like it!"
    }
    parsed = provider._parse_response(raw_response, {"episode_id": "EP100", "stage": "screenplay"})
    assert parsed["outputs"]["total_pages"] == 10
    assert len(parsed["outputs"]["scenes"]) == 1


def test_parse_malformed_json_raises_provider_validation_error():
    provider = OllamaProviderV2(stage="story")
    raw_response = {"response": "This is completely invalid and not JSON: {missing_quotes: 123"}
    with pytest.raises(ProviderValidationError) as exc_info:
        provider._parse_response(raw_response, {"episode_id": "EP100", "stage": "story"})
    assert "Failed to parse structured JSON" in str(exc_info.value) or "JSON" in str(exc_info.value)


def test_parse_non_dict_json_raises_provider_validation_error():
    provider = OllamaProviderV2(stage="story")
    raw_response = {"response": json.dumps(["an", "array", "not", "a", "dict"])}
    with pytest.raises(ProviderValidationError) as exc_info:
        provider._parse_response(raw_response, {"episode_id": "EP100", "stage": "story"})
    err_str = str(exc_info.value)
    assert "Failed to parse" in err_str or "dict" in err_str or "object" in err_str


# =========================================================================
# 3. Strict Validation Integration
# =========================================================================


def test_agent_stores_artifact_and_succeeds_on_valid_output(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = MockProviderV2("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    inputs = {"episode_id": "EP-VALID", "title": "Valid Story"}
    result = agent.run(inputs)
    assert result is not None
    assert "outputs" in result
    assert result["outputs"]["synopsis"] is not None

    # Check artifact was stored
    artifact_ref = artifact_mgr.get_latest_artifact("EP-VALID", "story")
    assert artifact_ref is not None


def test_agent_rejects_invalid_output_and_does_not_store_artifact(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    invalid_data = {"invalid_key": "no required fields present"}
    provider = InvalidSchemaProvider("story", invalid_data)
    state = PipelineState("EP-INVALID")
    state.add_stage("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    inputs = {"episode_id": "EP-INVALID", "title": "Invalid Story"}
    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        agent.run(inputs, pipeline_state=state)

    assert "validation failed" in str(exc_info.value).lower()

    # Verify stage marked as failed in pipeline state
    stage_state = state.get_stage("story")
    assert stage_state is not None
    assert stage_state.status.value in ["failed", "FAILED"]

    # Verify NO artifact was stored
    artifact_ref = artifact_mgr.get_latest_artifact("EP-INVALID", "story")
    assert artifact_ref is None
