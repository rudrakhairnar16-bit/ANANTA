# Requirement Traceability Matrix (RTM)
## Master Product Requirements Specification $\leftrightarrow$ ANANTA Engine Codebase

**Document Version:** 1.0.0  
**Source Specification:** `ANANTA_Master_Product_Requirements_Specification.md`  
**Target Codebase:** `ANANTA_MULTI_AGENT_ENGINE`  
**Status Legend:**
* **`[VERIFIED]`**: Fully implemented, tested, and actively verified in the codebase.
* **`[PARTIAL]`**: Core scaffolding, interfaces, or mock implementation exists, but real functionality or edge cases remain incomplete.
* **`[MOCK_ONLY]`**: Code returns synthetic mock data without performing actual generation or media processing.
* **`[MISSING]`**: No implementation exists in the current repository.
* **`[BLOCKED]`**: Blocked on external tool (e.g. FFmpeg installation) or hardware constraints (e.g. 6 GB VRAM limit).

---

### 1. Product Vision & Principles (Master Spec Section 1)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-VIS-01** | Support end-to-end anime production flow: Canon $\rightarrow$ screenplay $\rightarrow$ assets $\rightarrow$ media $\rightarrow$ edit $\rightarrow$ QA $\rightarrow$ final export. | 19-stage DAG orchestrators (`PipelineOrchestratorV2`, `ConcurrentPipelineOrchestrator`). | **`[PARTIAL]`** | `pipeline/orchestrator_v2.py`, `pipeline/concurrent_orchestrator.py` | Media generation stages currently output JSON text rather than actual visual/audio files. | Real media adapters (image, TTS, video). | Complete automated pipeline execution resulting in a playable MP4. | Phase A |
| **REQ-VIS-02** | Support both human-directed and controlled automated execution modes. | Batch automated CLI and DAG runner exist. | **`[PARTIAL]`** | `cli.py`, `pipeline/episode_pipeline.py` | Interactive human review checkpoints and pause/resume CLI flags are missing. | Terminal/Web review interface. | Operator can review, approve, reject, or edit outputs at designated stages. | Phase C |
| **REQ-VIS-03** | First goal is a short, watchable end-to-end prototype before expanding scope. | Prototype timeline assembler and mock WAV generator implemented. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py`, `providers/tts_provider.py` | Ingestion of real user-supplied images and speech audio to render live video. | Host FFmpeg binary, user assets. | 30–60s watchable prototype MP4 generated and validated. | Phase A |
| **REQ-VIS-04** | Core principles: Canon first, character consistency, truthful media labels, provider independence, hardware/cost awareness. | Immutable prompts, stage validator, mock/real provider metadata tags. | **`[VERIFIED]`** | `providers/base_v2.py`, `pipeline/artifacts.py`, `validation/schemas.py` | Visual/audio continuity checking engine to enforce consistency automatically. | Continuity Engine. | Artifacts record origin, provider identity, and checksum lineage. | Phase B |

---

### 2. Protected ANANTA Canon (Master Spec Section 2)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-CANON-01** | Core project identity: Title: ANANTA; Tagline: "The Gods Remember. Humanity Forgets."; Setting: Near-future India (2042). | Embedded in stage prompt templates and story agent defaults. | **`[VERIFIED]`** | `prompts/story_prompt.j2`, `agents/base_agent_v2.py` | Persistent queryable Canon Bible database. | Storage backend. | Prompts strictly use canonical titles and setting rules. | Phase B |
| **REQ-CANON-02** | Power progression strictly: Spark $\rightarrow$ Resonance $\rightarrow$ Epic State (No "Avatar State"). | Story and screenplay stage prompt instructions. | **`[VERIFIED]`** | `prompts/story_prompt.j2`, `prompts/screenplay_prompt.j2` | Automated validator preventing terminology regression in LLM outputs. | Schema validator / Continuity checker. | Schema/Continuity rejects outputs using forbidden terminology. | Phase C |
| **REQ-CANON-03** | Rudra's Epic State: "Unbound" (chaos, transformation, destruction, breaking limits). | Story prompts. | **`[VERIFIED]`** | `prompts/story_prompt.j2` | Character state tracking across scenes. | Character Bible. | Rudra's power states conform to canonical definitions. | Phase B |
| **REQ-CANON-04** | Aadhya's Epic State: "Shakti" (creation, restoration, renewal; not a mere love interest; blue thread removed from hair). | Character and story prompts. | **`[PARTIAL]`** | `prompts/character_prompt.j2` | Visual prompt generation enforcing removal of blue hair thread. | Visual prompt generator. | Visual prompts omit forbidden visual attributes. | Phase B |
| **REQ-CANON-05** | Ronit: Height ~150 cm; Kartikeya-inspired warrior; Vel Astra spear; Sena Mandala formation. | Character prompt templates. | **`[PARTIAL]`** | `prompts/character_prompt.j2` | Reference sheet conditioning maintaining height/weapon proportions. | ControlNet / Reference Adapter. | Visual assets depict Ronit with correct height ratio and Vel Astra. | Phase B |
| **REQ-CANON-06** | Ira: 19-year-old researcher/truth-holder investigating Astra Resonance and Divine Cycle. | Character prompt templates. | **`[VERIFIED]`** | `prompts/character_prompt.j2` | Long-term knowledge state persistence. | Character state store. | Screenplay preserves Ira's research role. | Phase B |
| **REQ-CANON-07** | Core team all aged 19: Rudra, Aadhya, Ronit, Ira. | Prompt templates. | **`[VERIFIED]`** | `prompts/character_prompt.j2` | Automated age and demographic consistency validation. | Continuity check. | Profiles consistently report age 19. | Phase C |
| **REQ-CANON-08** | Deliberate mysteries and unknowns must be marked `UNCONFIRMED` and never automatically resolved. | Policy in agent prompt guidelines. | **`[PARTIAL]`** | `prompts/story_prompt.j2` | Automated canon violation detector. | Continuity Engine. | Unconfirmed lore is not hallucinated as confirmed canon. | Phase C |

---

### 3. Media Origin & Lifecycle Labels (Master Spec Section 4)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-ORIGIN-01** | Distinct media origin labels: `mock`, `placeholder`, `synthetic`, `real_generated`, `user_supplied`. | Implemented in `AudioMetadata` and `TimelineManifest`. | **`[VERIFIED]`** | `providers/tts_provider.py`, `pipeline/timeline_assembler.py` | Universal tagging across all 19 stage artifact schemas. | `validation/schemas.py` | Every media asset carries explicit provenance label. | Phase A |
| **REQ-ORIGIN-02** | Lifecycle states: `draft`, `pending_review`, `approved`, `rejected`, `superseded`, `failed`, `blocked`, `stale`. | Stage states support `PENDING`, `COMPLETED`, `FAILED`, `BLOCKED`. | **`[PARTIAL]`** | `pipeline/pipeline_state.py`, `pipeline/artifacts.py` | Granular asset-level review states (`approved`, `rejected`, `superseded`). | Asset Manager. | Individual media assets can transition through review lifecycle. | Phase C |
| **REQ-ORIGIN-03** | Mock/placeholder media must be visibly labeled and never claimed as final anime. | Prototype banner in BMP placeholders, mock audio flags in manifest. | **`[VERIFIED]`** | `pipeline/timeline_assembler.py` | Automatic visual watermarking on generated video prototypes. | FFmpeg filtergraph. | Rendered prototypes contain visible prototype notice. | Phase A |
| **REQ-ORIGIN-04** | Prototype built with mock audio/placeholders must be labeled technical prototype. | `is_prototype`, `has_mock_audio`, `has_placeholder_visuals` flags in `RenderResult`. | **`[VERIFIED]`** | `pipeline/timeline_assembler.py` | Inclusion in final release packaging report. | Export Agent. | Final manifest explicitly reports prototype status. | Phase A |

---

### 4. Target Architecture & Provider Contract (Master Spec Section 5)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-ARCH-01** | Decouple: Project Store, Orchestrator, Agent Layer, Providers, Asset Manager, Continuity Engine, Timeline/Renderer, QA/Review, Packager, Observability. | Scaffolding exists for Orchestrator, Agents, Text Providers, Artifact Store. | **`[PARTIAL]`** | `pipeline/`, `agents/`, `providers/`, `observability/` | Dedicated Asset Manager, Continuity Engine, and Media Providers. | Architecture refactor. | Modular architecture with strict interface boundaries. | Phase B |
| **REQ-ARCH-02** | LLM agents produce plans/prompts; media providers generate actual bytes; asset manager versions them. | `VoiceAgentV2` coordinates text plan + TTS audio generation. | **`[PARTIAL]`** | `agents/base_agent_v2.py`, `providers/tts_provider.py` | Visual, motion, music, SFX agents lack media provider integration. | Media provider base. | All media stages produce both structured JSON and valid media files. | Phase B |
| **REQ-ARCH-03** | Standardized Provider Adapter Contract: preflight, creds, schemas, timeouts, cancel, costs, validation, explicit mock/real flags. | `BaseProviderV2` (text/LLM) and `BaseTTSProvider` (audio). | **`[PARTIAL]`** | `providers/base_v2.py`, `providers/tts_provider.py` | Generalized `BaseMediaProvider` for image, video, music, and lip-sync. | Base provider module. | Unified provider interface across text and media generation. | Phase B |
| **REQ-ARCH-04** | Do not push binary media into JSON artifacts; store filesystem paths and metadata. | `outputs/{episode_id}/voice/` and `outputs/{episode_id}/placeholders/`. | **`[VERIFIED]`** | `pipeline/artifacts.py`, `providers/tts_provider.py` | Centralized asset path resolver and integrity verifier. | Asset Library. | JSON artifacts contain only file paths, hashes, and metadata. | Phase A |
| **REQ-ARCH-05** | Sequential and Concurrent DAG Orchestration with thread safety. | `PipelineOrchestratorV2` & `ConcurrentPipelineOrchestrator`. | **`[VERIFIED]`** | `pipeline/orchestrator_v2.py`, `pipeline/concurrent_orchestrator.py` | Dynamic concurrency throttling based on GPU VRAM availability. | Hardware monitor. | 19 stages execute concurrently with thread-safe checkpoints. | Phase A |
| **REQ-ARCH-06** | Stage-scoped Circuit Breakers and Bounded Exponential Backoff with Jitter. | `CircuitBreaker` and `RetryPolicy` in `pipeline/execution.py`. | **`[VERIFIED]`** | `pipeline/execution.py`, `pipeline/retry.py` | Circuit breaker telemetry export. | Observability module. | Cascading failures are prevented via open circuit states. | Phase A |

---

### 5. The 19 Production Stages (Master Spec Section 6)

| Req ID | Stage | Master Spec Requirement | Current Status | Files Involved | Current Gap | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :---: |
| **REQ-STG-01** | `story` | Concept, synopsis, acts, beats, canon references. | **`[VERIFIED]`** | `agents/base_agent_v2.py`, `prompts/story_prompt.j2` | Real Ollama LLM integration verified; mock provider verified. | Phase A |
| **REQ-STG-02** | `screenplay` | Scenes, action, dialogue, speaker IDs, duration estimates. | **`[VERIFIED]`** | `prompts/screenplay_prompt.j2`, `validation/schemas.py` | Accurate per-scene page and duration estimation. | Phase A |
| **REQ-STG-03** | `scene_plan` | Shot breakdown, shot IDs, durations, framing, visual/audio needs. | **`[VERIFIED]`** | `prompts/scene_plan_prompt.j2`, `validation/schemas.py` | Visual asset reference linking. | Phase B |
| **REQ-STG-04** | `character` | Canon-linked profiles, states, turnaround references, voice IDs. | **`[PARTIAL]`** | `prompts/character_prompt.j2`, `validation/schemas.py` | Reference image asset generation and turnaround storage. | Phase B |
| **REQ-STG-05** | `world` | Environment rules, geography, weather, palette, props. | **`[PARTIAL]`** | `prompts/world_prompt.j2`, `validation/schemas.py` | Environment concept art image generation. | Phase B |
| **REQ-STG-06** | `storyboard` | Ordered panels/keyframes, framing, poses, image prompts. | **`[PARTIAL]`** | `prompts/storyboard_prompt.j2`, `validation/schemas.py` | Visual keyframe image generation. | Phase B |
| **REQ-STG-07** | `director` | Visual language, pacing, performance, scene direction. | **`[VERIFIED]`** | `prompts/director_prompt.j2`, `validation/schemas.py` | Integration with interactive director review gate. | Phase C |
| **REQ-STG-08** | `camera` | Shot size, lens/look, movement, lighting, composition. | **`[VERIFIED]`** | `prompts/camera_prompt.j2`, `validation/schemas.py` | Interpolation parameters for 2.5D camera moves. | Phase D |
| **REQ-STG-09** | `visual` | Actual image generation files (PNG/WebP), not only prompts. | **`[MOCK_ONLY]`** | `prompts/visual_prompt.j2`, `validation/schemas.py` | Real image generation provider (ComfyUI / SD / Cloud API). | Phase B |
| **REQ-STG-10** | `motion` | Actual video / 2.5D animation clips and metadata. | **`[MOCK_ONLY]`** | `prompts/motion_prompt.j2`, `validation/schemas.py` | Real image-to-video / pan-zoom motion engine. | Phase D |
| **REQ-STG-11** | `voice` | Dialogue extraction, casting, TTS synthesis, actual audio. | **`[PARTIAL]`** | `pipeline/dialogue_extractor.py`, `providers/tts_provider.py` | Live neural speech generation (`edge-tts` / `Kokoro`). | Phase A |
| **REQ-STG-12** | `music` | Score brief, themes, cues, music asset generation/selection. | **`[PARTIAL]`** | `prompts/music_prompt.j2`, `validation/schemas.py` | Audio catalog search and licensed track ingestion. | Phase B |
| **REQ-STG-13** | `bgm` | Cue placement, time ranges, transitions, volume ducking. | **`[PARTIAL]`** | `prompts/bgm_prompt.j2`, `validation/schemas.py` | Automated FFmpeg volume ducking curve application. | Phase D |
| **REQ-STG-14** | `sfx` | Spot effects, ambience, asset lookup/generation, timing. | **`[PARTIAL]`** | `prompts/sfx_prompt.j2`, `validation/schemas.py` | SFX sound library ingestion and timing placement. | Phase B |
| **REQ-STG-15** | `lipsync` | Audio-to-viseme/face mapping with confidence metadata. | **`[MOCK_ONLY]`** | `prompts/lipsync_prompt.j2`, `validation/schemas.py` | Real neural lip-sync model (Wav2Lip / LivePortrait). | Phase D |
| **REQ-STG-16** | `edit` | Timeline manifest, clip arrangement, transitions, sync. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py`, `prompts/edit_prompt.j2` | Full multi-track timeline XML conversion. | Phase A |
| **REQ-STG-17** | `adobe_export` | Valid FCPXML interchange referencing real media paths. | **`[MOCK_ONLY]`** | `prompts/adobe_export_prompt.j2`, `validation/schemas.py` | Valid FCPXML 1.10 generator tested in Premiere Pro. | Phase C |
| **REQ-STG-18** | `qa` | Canon, continuity, media, sync, subtitle, render review. | **`[PARTIAL]`** | `prompts/qa_prompt.j2`, `validation/schemas.py` | Automated video decode validation and continuity rule checker. | Phase C |
| **REQ-STG-19** | `export` | Master encode, variants, subtitles, project package. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py`, `prompts/export_prompt.j2` | Final release package bundling with checksum manifest. | Phase A |

---

### 6. Cross-Cutting Continuity System (Master Spec Section 7)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **REQ-CONT-01** | Track confirmed canon facts, chronology, dates, cause/effect, and character knowledge states. | General instructions in LLM prompts. | **`[MISSING]`** | None | Dedicated Canon State Store tracking facts, relationships, and knowledge per scene. | Knowledge Graph / DB. | Automated continuity checker detects knowledge anachronisms. | Phase C |
| **REQ-CONT-02** | Visual Continuity: Stable IDs for face, body, clothing, damage, lighting, prop positions, eyelines. | Prompt instructions. | **`[MISSING]`** | None | Visual continuity tracker verifying reference asset IDs across sequential shots. | Image Metadata Store. | Visual prompts include exact reference IDs and scene damage state. | Phase B |
| **REQ-CONT-03** | Audio Continuity: Stable voice profile IDs, language, accent, room tone, cue motifs, loudness limits. | Voice casting schema and audio metadata. | **`[PARTIAL]`** | `providers/tts_provider.py`, `validation/schemas.py` | Voice profile database and LUFS loudness normalization filter. | Audio DSP / FFmpeg. | Audio files maintain consistent sample rate and voice profile. | Phase B |
| **REQ-CONT-04** | Editorial Continuity: Shot order, transitions, match cuts, screen direction, A/V duration agreement. | `TimelineManifest` duration validation. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py` | Spatial screen direction / eyeline rule verification. | Editorial QA Module. | Manifest validates that clip durations match audio stems. | Phase A |
| **REQ-CONT-05** | Continuity Report: Check ID, category, severity, expected vs observed, status (`pass`/`warning`/`fail`). | QA schema contains `checks_passed` and `issues` arrays. | **`[PARTIAL]`** | `validation/schemas.py` | Structured `ContinuityReport` dataclass with machine-readable findings. | Continuity Engine. | QA outputs formal report with severity levels and suggested fixes. | Phase C |
| **REQ-CONT-06** | Canon-sensitive corrections require human approval before applying. | Manual pipeline re-run. | **`[MISSING]`** | None | Human approval gate for flagged continuity issues. | HITL Manager. | Flagged critical continuity errors halt progression until approved. | Phase C |

---

### 7. Asset Library & Character/World Bible (Master Spec Section 8)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| **REQ-ASSET-01** | Stable IDs: `character_id`, `location_id`, `prop_id`, `costume_id`, `voice_profile_id`, `asset_id`, `asset_version`. | Hardcoded IDs in mock data. | **`[PARTIAL]`** | `pipeline/episode_ids.py`, `validation/schemas.py` | Centralized UUID/slug entity registry enforcing uniqueness. | ID Generator. | All entities reference stable immutable IDs. | Phase B |
| **REQ-ASSET-02** | Character Profile: Turnarounds, expressions, fixed traits, prohibited changes, costumes, voice profile. | Character output schema. | **`[PARTIAL]`** | `validation/schemas.py`, `prompts/character_prompt.j2` | Visual asset library storing approved turnaround image files. | Asset Store. | Character profiles link to verified image turnaround files. | Phase B |
| **REQ-ASSET-03** | Asset Library: User uploads, references, images, audio, props, tags, dimensions, duration, hash, lineage. | `ArtifactStore` (JSON metadata only). | **`[PARTIAL]`** | `pipeline/artifacts.py` | Binary asset indexing, deduplication, thumbnail generation, and hash tracking. | Asset Library. | Binary files are indexed by SHA-256 and MIME type. | Phase B |
| **REQ-ASSET-04** | Reverse usage lookup: Find all scenes, shots, and episodes using a given asset or reference. | None. | **`[MISSING]`** | None | Cross-reference index linking assets to scene/shot IDs. | Asset Manager. | Asset query returns complete list of dependent scenes and shots. | Phase B |
| **REQ-ASSET-05** | Safe import and path validation: Path traversal prevention, safe file naming, missing file detection. | `validate_episode_id` and `TimelineAssembler` path validation. | **`[VERIFIED]`** | `pipeline/episode_ids.py`, `pipeline/timeline_assembler.py` | Centralized upload sanitizer. | Filesystem util. | Relative paths, symlinks, and path traversals are rejected. | Phase A |

---

### 8. Dialogue, Voice, Music & Sound Design (Master Spec Section 9)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| **REQ-AUDIO-01** | Unique Dialogue Record: `dialogue_id`, scene, order, speaker, text, emotion, duration, timing. | `DialogueLine` and `AudioMetadata` dataclasses. | **`[VERIFIED]`** | `pipeline/dialogue_extractor.py`, `providers/tts_provider.py` | Alignment phoneme timestamp storage. | TTS Alignment. | Screenplay dialogue is extracted sequentially without data loss. | Phase A |
| **REQ-AUDIO-02** | TTS Provider Adapters: Local/cloud TTS, stable voice mapping, format conversion, decodability checks. | `MockTTSProvider`, `EdgeTTSProvider`, `KokoroTTSProvider`, `PiperTTSProvider`. | **`[VERIFIED]`** | `providers/tts_provider.py`, `providers/registry_v2.py` | Live synthesis smoke test with installed model. | Python TTS pkg. | Provider synthesizes playable WAV/MP3 files. | Phase A |
| **REQ-AUDIO-03** | Music / Score: Separate score brief from asset selection; cue ID, mood, tempo, track file, mix level. | `music` and `bgm` schemas and prompt templates. | **`[PARTIAL]`** | `prompts/music_prompt.j2`, `validation/schemas.py` | Audio catalog integration and licensed track file mapping. | Audio Catalog. | BGM tracks reference actual playable audio files. | Phase B |
| **REQ-AUDIO-04** | SFX / Ambience: Spot effects, library search, timing, distance, ambience across cuts. | `sfx` schema and prompt template. | **`[PARTIAL]`** | `prompts/sfx_prompt.j2`, `validation/schemas.py` | Local SFX library indexing and sample placement. | Sound Library. | SFX cues map to audio assets placed on timeline. | Phase B |
| **REQ-AUDIO-05** | Final Mix: Dialogue intelligibility, BGM ducking, clipping/peak checks, separate stems. | `TimelineAssembler` `amix` filter. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py` | Dynamic sidechain compression / ducking and multi-stem export. | FFmpeg filter. | Dialogue remains intelligible over BGM; stems exported. | Phase D |

---

### 9. Visual, Motion, Timeline & Rendering (Master Spec Sections 10 & 11)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| **REQ-VISUAL-01**| Image Generation Adapter: Prompt from shot direction + canon + references, aspect ratio, seed, bytes. | Prompt templates in `visual_prompt.j2`. | **`[MISSING]`** | None | Real image diffusion adapter (ComfyUI / SD / Cloud API). | Image Backend. | Generates PNG/WebP image files matching shot direction. | Phase B |
| **REQ-VISUAL-02**| Motion Capability Ladder: 1. Still image timeline with pan/zoom (MVP) $\rightarrow$ 2. Parallax $\rightarrow$ 3. Video gen. | Still image timeline assembler implemented for MVP. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py` | Pan/zoom Ken Burns FFmpeg filters and video diffusion adapter. | FFmpeg / SVD. | MP4 includes animated pan/zoom moves across still keyframes. | Phase A |
| **REQ-TIMELINE-01**| Timeline Manifest: Versioned source of truth, FPS, resolution, clips, audio tracks, transitions. | `TimelineManifest` and `TimelineClip` dataclasses. | **`[VERIFIED]`** | `pipeline/timeline_assembler.py` | Full transition filtergraph support (dissolve, wipe). | FFmpeg complex filter. | Manifest serializes to/from JSON and validates durations. | Phase A |
| **REQ-TIMELINE-02**| Video Renderer: FFmpeg-based renderer, atomic publish, corrupt media rejection, MP4 validation. | `TimelineAssembler.render()` with concat script and subprocess. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py` | Live rendering blocked on host FFmpeg installation. | Host FFmpeg. | Generates 1280x720 24FPS H.264/AAC MP4 video file. | Phase A |
| **REQ-TIMELINE-03**| Subtitle Generation: Standard `.srt` format, dialogue timecode alignment, speaker tags. | `TimelineAssembler.generate_subtitles_srt()`. | **`[VERIFIED]`** | `pipeline/timeline_assembler.py` | Subtitle burn-in video filter option. | FFmpeg. | Generates valid `.srt` matching audio timestamps. | Phase A |
| **REQ-TIMELINE-04**| Adobe Premiere Interchange: Valid FCPXML referencing real media paths with relink validation. | Schema and mock XML text block in `adobe_export`. | **`[MOCK_ONLY]`** | `prompts/adobe_export_prompt.j2`, `validation/schemas.py` | FCPXML 1.10 builder with absolute media file URIs tested in Premiere. | Premiere test. | FCPXML imports cleanly into Adobe Premiere Pro. | Phase C |

---

### 10. Human Review, QA, Release & Persistence (Master Spec Sections 12–18)

| Req ID | Exact Requirement | Existing Implementation | Status | Files Involved | Missing Functionality | Dependencies | Acceptance Criteria | Phase |
| :--- | :--- | :--- | :---: | :--- | :--- | :--- | :--- | :--- |
| **REQ-HITL-01** | Configurable Review Gates: Screenplay, References, Storyboard, Voice, Rough Cut, Final QA. | `approval_status` field in schemas. | **`[PARTIAL]`** | `validation/schemas.py`, `pipeline/pipeline_state.py` | Interactive pause-at-gate orchestrator hook and review CLI. | CLI Reviewer. | Pipeline pauses at configured gates until approved. | Phase C |
| **REQ-DEP-01**  | Selective Regeneration: Upstream changes mark descendants `stale`; regenerate only affected branches. | Downstream failure isolation implemented (`BLOCKED`). | **`[PARTIAL]`** | `pipeline/concurrent_orchestrator.py`, `pipeline/execution.py` | Staleness propagation on artifact mutation. | DAG Invalidator. | Modifying a scene regenerates only that scene's shots and audio. | Phase C |
| **REQ-QA-01**   | Technical Media QA: Decodability, duration matching, missing frame detection, audio clipping. | Subprocess exit code validation. | **`[PARTIAL]`** | `pipeline/timeline_assembler.py` | FFprobe media stream verification and loudness check. | FFprobe. | QA verifies audio and video streams decode without errors. | Phase C |
| **REQ-PERSIST-01**| Persistence & Recovery: Checkpoint/resume, atomic I/O, SHA-256 checksums, crash recovery. | `ArtifactStore`, `CheckpointManager`, `atomic_write_text`. | **`[VERIFIED]`** | `pipeline/artifacts.py`, `pipeline/atomic_io.py` | Automated telemetry export (`_pipeline_telemetry.json`). | Telemetry Logger. | System recovers from simulated crash at any pipeline stage. | Phase A |
| **REQ-SEC-01**  | Security & Rights: No secrets in code/logs, path traversal prevention, local-only execution mode. | Environment-based config, input path sanitization. | **`[VERIFIED]`** | `config_v2.py`, `pipeline/episode_ids.py` | Automated secret scrubber for provider debug logs. | Redactor filter. | Secrets are never logged or committed. | Phase A |
| **REQ-HW-01**   | Hardware Constraints: Windows, RTX 3050 6GB VRAM, sequential GPU tasks, no heavy auto-downloads. | Local-first design, Ollama integration, memory management. | **`[VERIFIED]`** | `config_v2.py`, `providers/base_v2.py` | GPU memory manager unloading LLM before image generation. | Torch/CUDA util. | Peak VRAM usage remains under 6 GB without OOM crashes. | Phase B |
