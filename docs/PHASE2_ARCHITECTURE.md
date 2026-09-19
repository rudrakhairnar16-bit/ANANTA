# Phase 2 Architecture: ANANTA Production Engine

## Overview
Upgrade from basic functional pipeline to production-oriented, extensible architecture.

## Core Components

### 1. Enhanced Provider Abstraction (providers/base_v2.py)
- **BaseProviderV2**: Abstract base with sync/async, structured responses, metrics
- **ProviderConfig**: Dataclass for provider configuration
- **ProviderResponse**: Standardized response with metadata, metrics, errors
- **MockProviderV2**: Deterministic mock with seed support, latency simulation
- **ProviderMetrics**: Latency, token usage, error rates, success rates

### 2. Provider Registry with Model Routing (providers/registry_v2.py)
- **ProviderRegistry**: Central registry with lazy loading, health checks
- **ModelRouter**: Routes stages to providers based on config
- **ProviderFactory**: Creates providers from config
- **HealthChecker**: Periodic health checks for external providers

### 3. Pipeline State Management (pipeline/state.py)
- **PipelineState**: Persistent state with checkpointing
- **StageState**: Per-stage state (pending, running, completed, failed, skipped)
- **CheckpointManager**: Save/restore pipeline state
- **StateStore**: File-based persistence with versioning

### 4. Stage Dependency Graph (pipeline/dependencies.py)
- **DependencyGraph**: DAG of stage dependencies
- **StageSpec**: Stage specification with inputs, outputs, dependencies
- **TopologicalExecutor**: Executes stages respecting dependencies
- **ParallelExecutor**: Runs independent stages in parallel

### 5. Structured Logging (observability/logging.py)
- **StructuredLogger**: JSON logging with correlation IDs
- **StageLogger**: Per-stage logging context
- **PipelineLogger**: Pipeline-level logging with summary
- **LogContext**: Thread-local context for correlation

### 6. Artifact Management (pipeline/artifacts.py)
- **ArtifactStore**: Versioned artifact storage
- **ArtifactMetadata**: Schema, checksum, lineage
- **ArtifactReference**: Pointers to artifacts for stage inputs

### 7. Failure Recovery (pipeline/recovery.py)
- **RetryPolicy**: Configurable retry with backoff
- **CircuitBreaker**: Prevent cascading failures
- **RecoveryStrategy**: Retry, skip, rollback, manual
- **FailureClassifier**: Transient vs permanent failures

### 8. Input/Output Validation (validation/schemas.py)
- **StageSchema**: JSON Schema per stage
- **Validator**: Validates inputs/outputs against schemas
- **ValidationResult**: Detailed validation errors

### 9. Enhanced Configuration (config_v2.py)
- **ProviderSettings**: Per-provider configuration
- **StageSettings**: Per-stage configuration
- **ExecutionSettings**: Parallel, timeout, retry config
- **ObservabilitySettings**: Logging, metrics, tracing config

### 10. Pipeline Orchestrator v2 (pipeline/orchestrator_v2.py)
- **PipelineOrchestrator**: Main orchestrator with all features
- **ExecutionContext**: Runtime context for execution
- **ProgressTracker**: Real-time progress tracking
- **EventBus**: Stage events for observers

## Backward Compatibility
- All Phase 1 interfaces preserved
- Existing 21 tests must pass
- 19-stage pipeline must work identically
- Mock mode fully functional
- Ollama exclusive to StoryAgent (configurable)
- YAML → env precedence intact