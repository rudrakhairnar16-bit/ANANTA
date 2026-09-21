# Phase 2 Architecture: ANANTA Production Engine

## Overview
Upgrade from basic functional pipeline to production-oriented, extensible architecture.

## Architecture Relationship

V1 and V2 are **parallel implementations** that share the same 19-stage pipeline concept:

- **V1** (`pipeline/episode_pipeline.py`): Original sequential pipeline using `agents/base_agent.py`, `providers/base.py`, `config.py`
- **V2** (`pipeline/orchestrator_v2.py`): Production pipeline using `agents/base_agent_v2.py`, `providers/base_v2.py`, `config_v2.py`

Both pipelines execute the same 19 stages with the same mock data. V2 adds state management, validation, structured logging, artifact versioning, and failure recovery.

## Runtime Flow

### V1 Pipeline
```
episode_pipeline.py
  → get_agent(stage)           # agents/base_agent.py
    → get_provider(stage)      # providers/registry.py
      → MockProvider / OllamaProvider
    → agent.run(inputs)
      → validate_inputs()
      → provider.generate(inputs)
      → write output to outputs/
      → return merged data
  → next stage
```

### V2 Pipeline
```
orchestrator_v2.py
  → create_initial_state()     # pipeline/state.py
  → get_default_dependency_graph()  # pipeline/dependencies.py
  → for stage in execution_order:
    → get_agent_v2(stage)      # agents/base_agent_v2.py
      → get_provider_for_stage_v2()  # providers/registry_v2.py
        → MockProviderV2 / OllamaProviderV2
    → agent.run(inputs, pipeline_state)
      → validate_inputs()       # checks required_inputs in top-level + outputs
      → recovery_manager.execute_stage()  # pipeline/recovery.py
        → provider.generate_sync(inputs)
          → returns ProviderResponse with metrics
      → validator.validate_output()  # validation/schemas.py
      → artifact_manager.store_stage_output()  # pipeline/artifacts.py
      → pipeline_state.update_stage()
      → checkpoint_manager.checkpoint()
      → return merged data (outputs accumulated, not overwritten)
  → save state, create summary
```

## Core Components

### 1. Enhanced Provider Abstraction (providers/base_v2.py)
- **BaseProviderV2**: Abstract base with sync/async, structured responses, metrics
- **ProviderConfig**: Dataclass for provider configuration
- **ProviderResponse**: Standardized response with success/error, data, metrics
- **MockProviderV2**: Deterministic mock with seed support, latency simulation
- **OllamaProviderV2**: Ollama integration with error classification
- **ProviderMetrics**: Latency, token usage, error rates, success rates

### 2. Provider Registry with Model Routing (providers/registry_v2.py)
- **ProviderRegistry**: Central registry with lazy loading, caching
- **ModelRouter**: Routes stages to providers based on config
- **Routing**: Only "story" stage routes to Ollama when enabled; all others use mock

### 3. Pipeline State Management (pipeline/state.py)
- **PipelineState**: Persistent state tracking all stages
- **StageState**: Per-stage state (PENDING, RUNNING, COMPLETED, FAILED, SKIPPED, RETRYING)
- **CheckpointManager**: Save/restore pipeline state to `outputs/state/`
- **StateStore**: File-based persistence as JSON

### 4. Stage Dependency Graph (pipeline/dependencies.py)
- **DependencyGraph**: DAG of 19 stage dependencies
- **StageSpec**: Stage specification with required_inputs, produces_outputs, dependencies
- **Execution**: Topological sort determines stage ordering
- **Cycle detection**: Raises ValueError if cycles detected

### 5. Structured Logging (observability/logging.py)
- **StructuredLogger**: JSON logging with timestamps, levels, context
- **LogContext**: Thread-local context with correlation_id, pipeline_id, episode_id, stage
- **Integration**: Used by V2 orchestrator and V2 agents

### 6. Artifact Management (pipeline/artifacts.py)
- **ArtifactStore**: Versioned storage in `outputs/artifacts/{episode_id}/`
- **ArtifactManager**: High-level API for storing stage outputs
- **Versioning**: Auto-increments version per stage per episode
- **Lineage**: Tracks input artifacts and output keys
- **Index**: JSON index file for fast lookup

### 7. Failure Recovery (pipeline/recovery.py)
- **RetryPolicy**: Exponential backoff with jitter
- **CircuitBreaker**: Opens after 5 failures, closes after 2 successes
- **FailureClassifier**: Classifies errors as TRANSIENT, PERMANENT, or UNKNOWN
- **RecoveryPlanner**: Decides RETRY, SKIP, ABORT, or MANUAL based on failure type
- **StageRecoveryManager**: Executes stages with automatic retry and recovery

### 8. Input/Output Validation (validation/schemas.py)
- **StageValidator**: JSON Schema validation per stage
- **Schemas**: story, screenplay, character, world, generic_stage_output
- **Fallback**: Uses jsonschema if installed, otherwise basic type checking
- **Integration**: Called in BaseAgentV2.run() - validates output after generation

### 9. Enhanced Configuration (config_v2.py)
- **Settings**: Ollama, Pipeline, Output, Observability sections
- **StageSettings**: Per-stage provider config, timeouts, retries
- **Precedence**: config.yaml defaults → YAML values → environment variables

### 10. Pipeline Orchestrator V2 (pipeline/orchestrator_v2.py)
- **PipelineOrchestratorV2**: Main orchestrator
- **ExecutionContext**: Runtime context with state, artifacts, validation
- **Features**: Checkpointing, resume, structured logging, artifact versioning

## Data Flow Between Stages

Each stage receives the accumulated data from all previous stages. The `outputs` dictionary is accumulated (not overwritten) so downstream stages can access outputs from any upstream stage.

```python
# After story: outputs = {synopsis, themes, acts, beats}
# After screenplay: outputs = {synopsis, themes, acts, beats, scenes, total_pages}
# After music: outputs = {synopsis, themes, acts, beats, scenes, total_pages, cues, ...}
```

## Validation in Execution Path

Validation is wired into `BaseAgentV2.run()`:

1. **Input validation**: Checks `required_inputs` exist in top-level or `outputs` dict
2. **Execute**: Provider generates output via recovery manager (with retry)
3. **Output validation**: Validates output against JSON Schema (warnings only, non-blocking)
4. **Persist**: Store artifact, update pipeline state, checkpoint

## Backward Compatibility
- All Phase 1 interfaces preserved (V1 pipeline unchanged)
- Existing 21 V1 tests pass
- 19-stage pipeline works in both V1 and V2
- Mock mode fully functional in both V1 and V2
- Ollama exclusive to StoryAgent (configurable)
- YAML → env precedence intact in both V1 and V2

## Current Limitations
- V1 uses `print()` for output; V2 uses structured logging
- V1 has no state persistence; V2 has checkpointing
- V1 has no validation; V2 validates inputs and outputs
- Recovery state (circuit breaker) is not persisted across runs
- Parallel stage execution is defined in dependency graph but not implemented in orchestrator
- Async provider support is not implemented
