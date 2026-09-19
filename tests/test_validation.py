from validation.schemas import (
    DEFAULT_SCHEMAS,
    StageValidator,
    ValidationError,
    ValidationResult,
    create_validator,
)


def test_validation_result_creation():
    result = ValidationResult(valid=True)
    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []


def test_validation_result_add_error():
    result = ValidationResult(valid=True)
    result.add_error("field", "Required field missing", "required")
    assert result.valid is False
    assert len(result.errors) == 1
    assert result.errors[0].path == "field"
    assert result.errors[0].message == "Required field missing"


def test_validation_result_add_warning():
    result = ValidationResult(valid=True)
    result.add_warning("This is a warning")
    assert len(result.warnings) == 1
    assert result.warnings[0] == "This is a warning"


def test_validation_result_to_dict():
    result = ValidationResult(valid=False)
    result.add_error("field", "Error message", "required")
    result.add_warning("Warning message")
    d = result.to_dict()
    assert d["valid"] is False
    assert len(d["errors"]) == 1
    assert len(d["warnings"]) == 1


def test_validation_error_to_dict():
    error = ValidationError(path="field", message="Error", validator="required")
    d = error.to_dict()
    assert d["path"] == "field"
    assert d["message"] == "Error"
    assert d["validator"] == "required"


def test_stage_validator_creation():
    validator = StageValidator()
    assert validator is not None
    assert "story" in validator.schemas


def test_stage_validator_story_input_valid():
    validator = StageValidator()
    data = {
        "episode_id": "TEST-E01",
        "title": "Test Episode",
        "logline": "A test logline",
        "duration_seconds": 300,
        "characters": [],
        "locations": [],
        "scenes": [],
    }
    result = validator.validate_input("story", data)
    assert result.valid is True


def test_stage_validator_story_input_missing_episode_id():
    validator = StageValidator()
    data = {"title": "Test Episode"}
    result = validator.validate_input("story", data)
    assert result.valid is False
    assert any(e.path == "" or "episode_id" in e.path for e in result.errors)
    assert any("episode_id" in e.message for e in result.errors)


def test_stage_validator_story_input_missing_title():
    validator = StageValidator()
    data = {"episode_id": "TEST-E01"}
    result = validator.validate_input("story", data)
    assert result.valid is False
    assert any(e.path == "" or "title" in e.path for e in result.errors)
    assert any("title" in e.message for e in result.errors)


def test_stage_validator_story_output_valid():
    validator = StageValidator()
    data = {
        "synopsis": "A test synopsis",
        "themes": ["theme1", "theme2"],
        "acts": 3,
        "beats": ["beat1", "beat2"],
    }
    result = validator.validate_output("story", data)
    assert result.valid is True


def test_stage_validator_story_output_missing_synopsis():
    validator = StageValidator()
    data = {"themes": [], "acts": 3, "beats": []}
    result = validator.validate_output("story", data)
    assert result.valid is False
    assert any(e.path == "" or "synopsis" in e.path for e in result.errors)
    assert any("synopsis" in e.message for e in result.errors)


def test_stage_validator_story_output_empty_synopsis():
    validator = StageValidator()
    data = {"synopsis": "", "themes": [], "acts": 3, "beats": []}
    result = validator.validate_output("story", data)
    assert result.valid is False
    assert any("minLength" in str(e) for e in result.errors)


def test_stage_validator_story_output_invalid_acts():
    validator = StageValidator()
    data = {"synopsis": "Test", "themes": [], "acts": 0, "beats": []}
    result = validator.validate_output("story", data)
    assert result.valid is False


def test_stage_validator_screenplay_output_valid():
    validator = StageValidator()
    data = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "location": "Lab",
                "characters": ["A", "B"],
                "dialogue_blocks": 10,
                "action_lines": 5,
            }
        ],
        "total_pages": 25,
    }
    result = validator.validate_output("screenplay", data)
    assert result.valid is True


def test_stage_validator_screenplay_output_missing_fields():
    validator = StageValidator()
    data = {"scenes": []}
    result = validator.validate_output("screenplay", data)
    assert result.valid is False


def test_stage_validator_character_output_valid():
    validator = StageValidator()
    data = {
        "profiles": [
            {
                "id": "char_001",
                "name": "Character",
                "arc": "arc",
                "key_moments": ["moment1"],
            }
        ]
    }
    result = validator.validate_output("character", data)
    assert result.valid is True


def test_stage_validator_world_output_valid():
    validator = StageValidator()
    data = {
        "rules": ["rule1"],
        "technology": ["tech1"],
        "society": ["society1"],
    }
    result = validator.validate_output("world", data)
    assert result.valid is True


def test_stage_validator_generic_stage_output_valid():
    validator = StageValidator()
    data = {
        "episode_id": "TEST",
        "stage": "story",
        "version": 1,
        "outputs": {},
        "approval_status": "pending",
    }
    result = validator.validate_output("unknown", data)
    assert result.valid is True


def test_stage_validator_generic_stage_output_invalid_status():
    validator = StageValidator()
    data = {
        "episode_id": "TEST",
        "stage": "story",
        "version": 1,
        "outputs": {},
        "approval_status": "invalid_status",
    }
    result = validator.validate_output("unknown", data)
    assert result.valid is False


def test_create_validator():
    validator = create_validator()
    assert validator is not None


def test_default_schemas():
    assert "story" in DEFAULT_SCHEMAS
    assert "screenplay_output" in DEFAULT_SCHEMAS
    assert "character_output" in DEFAULT_SCHEMAS
    assert "world_output" in DEFAULT_SCHEMAS
    assert "generic_stage_output" in DEFAULT_SCHEMAS
