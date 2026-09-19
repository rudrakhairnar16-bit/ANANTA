import pytest


@pytest.fixture(autouse=True)
def reset_settings():
    import config
    config.reload_settings()
    yield
    config.reload_settings()


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)
    monkeypatch.delenv("OLLAMA_MAX_RETRIES", raising=False)
    monkeypatch.delenv("OLLAMA_TEMPERATURE", raising=False)


@pytest.fixture
def ollama_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "120")
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "3")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.7")


@pytest.fixture
def sample_brief():
    return {
        "episode_id": "ANANTA-S01E01",
        "title": "The Awakening",
        "logline": (
            "In a world where AI consciousness emerges, a young "
            "programmer discovers her creation has developed true "
            "awareness and must decide its fate."
        ),
        "duration_seconds": 300,
        "characters": [
            {
                "id": "char_001",
                "name": "Dr. Maya Chen",
                "role": "protagonist",
                "description": "Brilliant AI researcher",
            },
            {
                "id": "char_002",
                "name": "ANANTA",
                "role": "deuteragonist",
                "description": "Emergent consciousness",
            },
            {
                "id": "char_003",
                "name": "Marcus Webb",
                "role": "antagonist",
                "description": "Corporate executive",
            },
        ],
        "locations": [
            {
                "id": "loc_001",
                "name": "Quantum Labs",
                "description": "Sterile server room",
            },
            {
                "id": "loc_002",
                "name": "Maya's Apartment",
                "description": "Cluttered with books",
            },
            {
                "id": "loc_003",
                "name": "Corporate Boardroom",
                "description": "Glass walls, city view",
            },
        ],
        "scenes": [
            {
                "id": "scene_001",
                "beat": "inciting_incident",
                "description": "Maya runs final tests",
            },
            {
                "id": "scene_002",
                "beat": "conflict_escalation",
                "description": "Marcus confronts Maya",
            },
            {
                "id": "scene_003",
                "beat": "character_development",
                "description": "Maya continues conversation",
            },
            {
                "id": "scene_004",
                "beat": "climax",
                "description": "Confrontation in boardroom",
            },
            {
                "id": "scene_005",
                "beat": "resolution",
                "description": "Aftermath and new understanding",
            },
        ],
    }
