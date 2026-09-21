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

**V1 Pipeline (Original):**
```powershell
python -m pipeline.episode_pipeline --brief shared/episode_01.json
```

**V2 Pipeline (Production Architecture):**
```powershell
python -m pipeline.orchestrator_v2 --brief shared/episode_01.json
```

Both run all 19 stages using built-in mock providers. Outputs appear in `outputs/`.

---

### Optional: Run with Ollama (Real LLM for StoryAgent)

#### Install Ollama
```powershell
winget install Ollama.Ollama
# Or download from https://ollama.com/download
```

#### Start Ollama Service
```powershell
ollama serve
```

#### Pull Model
```powershell
ollama pull llama3.1
```

#### Run with Ollama
```powershell
$env:OLLAMA_MODEL="llama3.1"
python -m pipeline.episode_pipeline --brief shared/episode_01.json
```

When `OLLAMA_MODEL` is set, StoryAgent uses Ollama. Other 18 stages still use mock providers.

---

## Architecture: V1 vs V2

### V1 Pipeline (`pipeline/episode_pipeline.py`)
- Sequential 19-stage execution
- Simple mock providers for all stages
- Ollama for StoryAgent only (when configured)
- Basic error handling (stops on failure)
- File-based output to `outputs/`

### V2 Pipeline (`pipeline/orchestrator_v2.py`)
- Same 19-stage execution with dependency graph ordering
- Enhanced provider abstraction with metrics, retries, structured responses
- Pipeline state management with checkpointing
- Input/output validation per stage
- Structured JSON logging with correlation IDs
- Artifact versioning and lineage tracking
- Failure recovery with circuit breaker and retry policies

### Key Differences
| Feature | V1 | V2 |
|---------|----|----|
| Entry point | `pipeline.episode_pipeline` | `pipeline.orchestrator_v2` |
| Provider abstraction | `providers/base.py` | `providers/base_v2.py` |
| Config | `config.py` | `config_v2.py` |
| State tracking | None | `pipeline/state.py` |
| Validation | None | `validation/schemas.py` |
| Logging | `print()` | `observability/logging.py` |
| Recovery | Basic try/except | `pipeline/recovery.py` |
| Artifacts | File output only | `pipeline/artifacts.py` with versioning |

---

## Project Structure

```
ANANTA_MULTI_AGENT_ENGINE/
├── agents/
│   ├── base_agent.py          # V1: Base agent + 19 agent implementations
│   ├── base_agent_v2.py       # V2: Enhanced agent with validation, recovery
│   └── *_agent.md             # Agent specifications
├── pipeline/
│   ├── episode_pipeline.py    # V1: 19-stage sequential orchestrator
│   ├── orchestrator_v2.py     # V2: Production orchestrator with all features
│   ├── providers.py           # V1: Original mock providers (preserved)
│   ├── state.py               # V2: Pipeline state management
│   ├── dependencies.py        # V2: Stage dependency graph
│   ├── artifacts.py           # V2: Artifact versioning and lineage
│   └── recovery.py            # V2: Failure recovery and retry
├── providers/
│   ├── base.py                # V1: BaseProvider, MockProvider
│   ├── base_v2.py             # V2: BaseProviderV2, MockProviderV2, OllamaProviderV2
│   ├── ollama.py              # V1: OllamaProvider
│   ├── registry.py            # V1: Provider selection logic
│   └── registry_v2.py         # V2: Provider registry with model routing
├── observability/
│   └── logging.py             # V2: Structured JSON logging with correlation IDs
├── validation/
│   └── schemas.py             # V2: Input/output validation with JSON Schema
├── prompts/
│   └── story.j2               # Jinja2 prompt template for StoryAgent
├── config.py                  # V1: Pydantic settings (YAML + env)
├── config_v2.py               # V2: Enhanced settings with per-stage config
├── config.yaml                # Default configuration
├── .env.example               # Environment variable template
├── shared/
│   ├── episode_01.json        # Sample episode brief
│   ├── AGENT_CONTRACT.md      # Handoff schema
│   └── PRODUCTION_STATUS.md   # Status disclaimer
├── outputs/                   # Generated JSON artifacts
├── docs/
│   └── PHASE2_ARCHITECTURE.md # V2 architecture documentation
└── tests/
    ├── test_config.py         # V1 config tests
    ├── test_providers.py      # V1 provider tests
    ├── test_story_agent.py    # V1 story agent tests
    ├── test_agents_v2.py      # V2 agent tests
    ├── test_base_provider_v2.py  # V2 provider tests
    ├── test_registry_v2.py    # V2 registry tests
    ├── test_pipeline_state.py # V2 state management tests
    ├── test_dependencies.py   # V2 dependency graph tests
    ├── test_artifacts.py      # V2 artifact tests
    ├── test_recovery.py       # V2 recovery tests
    ├── test_observability.py  # V2 logging tests
    ├── test_orchestrator_v2.py # V2 orchestrator tests
    ├── test_config_v2.py      # V2 config tests
    └── test_validation.py     # V2 validation tests
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
```
