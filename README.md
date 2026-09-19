# ANANTA Multi-Agent Production Engine

A local-first orchestration scaffold for turning episode briefs into production artifacts.

## Quick Start (Windows)

### 1. Create Virtual Environment
```powershell
cd ANANTA_MULTI_AGENT_ENGINE
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```powershell
pip install -e ".[dev]"
```

### 3. Run in Mock Mode (Default - No Ollama Required)
```powershell
python -m pipeline.episode_pipeline --brief shared/episode_01.json
```
All 19 stages will run using built-in mock providers. Outputs appear in `outputs/`.

---

### Optional: Run with Ollama (Real LLM for StoryAgent)

#### Install Ollama
```powershell
# Option A: Winget
winget install Ollama.Ollama

# Option B: Download from https://ollama.com/download
```

#### Start Ollama Service
```powershell
# In a separate terminal window:
ollama serve
```

#### Pull Model
```powershell
ollama pull llama3.1
```

#### Configure Environment
```powershell
copy .env.example .env
# Edit .env and set:
# OLLAMA_MODEL=llama3.1
# OLLAMA_BASE_URL=http://localhost:11434
```

#### Run with Ollama
```powershell
$env:OLLAMA_MODEL="llama3.1"
$env:OLLAMA_BASE_URL="http://localhost:11434"
python -m pipeline.episode_pipeline --brief shared/episode_01.json
```

**Note**: When `OLLAMA_MODEL` is set, StoryAgent uses Ollama. If Ollama is unavailable, a clear error is raised with instructions. Other 18 stages still use mock providers.

---

## Project Structure

```
ANANTA_MULTI_AGENT_ENGINE/
├── agents/
│   ├── base_agent.py          # Base agent class + 19 agent implementations
│   └── *_agent.md             # Agent specifications
├── pipeline/
│   ├── episode_pipeline.py    # 19-stage sequential orchestrator
│   └── providers.py           # Original mock providers (preserved)
├── providers/                 # NEW: Real provider implementations
│   ├── base.py                # BaseProvider, MockProvider
│   ├── ollama.py              # OllamaProvider
│   └── registry.py            # Provider selection logic
├── prompts/
│   └── story.j2               # Jinja2 prompt template for StoryAgent
├── config.py                  # Pydantic settings (YAML + env)
├── config.yaml                # Default configuration
├── .env.example               # Environment variable template
├── shared/
│   ├── episode_01.json        # Sample episode brief
│   ├── AGENT_CONTRACT.md      # Handoff schema
│   └── PRODUCTION_STATUS.md   # Status disclaimer
├── outputs/                   # Generated JSON artifacts
└── tests/
    ├── test_config.py
    ├── test_providers.py
    └── test_story_agent.py
```

## Pipeline Stages (19)

1. **story** - Synopsis, themes, acts, beats
2. **screenplay** - Scene breakdown, dialogue blocks
3. **scene_plan** - Shots, camera setups, VFX notes
4. **character** - Character arcs, key moments
5. **world** - Rules, technology, society
6. **storyboard** - Panels, key frames
7. **director** - Vision, shot style, pacing
8. **camera** - Lenses, movement, lighting
9. **visual** - Concept art, VFX, color palette
10. **motion** - Animation style, sequences
11. **voice** - Casting, direction, recording notes
12. **music** - Themes, cues, instrumentation
13. **bgm** - Scene tracks, ducking, transitions
14. **sfx** - Design, spot effects, ambience
15. **lipsync** - Phoneme maps, viseme schedule
16. **edit** - Assembly, pacing, transitions
17. **adobe_export** - Timeline XML, markers CSV
18. **qa** - Contract compliance checks
19. **export** - Deliverables spec

## Agent Contract

Every stage output contains:
- `episode_id`, `stage`, `version`, `generated_at`
- `inputs` (full previous stage data)
- `outputs` (stage-specific data)
- `assumptions`, `warnings`, `approval_status`

## Testing

```powershell
# Run all tests
pytest

# Run with coverage
pytest --cov=agents --cov=pipeline --cov=providers --cov=config

# Run specific test file
pytest tests/test_story_agent.py -v
```

## Development

```powershell
# Format code
ruff format .

# Lint
ruff check .

# Type check (if adding pyright/mypy later)
# pyright
```