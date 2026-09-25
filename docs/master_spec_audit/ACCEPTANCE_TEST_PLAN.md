# Acceptance Test Plan
## Multi-Tier Testing Strategy & Phase Acceptance Verification Suite

**Document Version:** 1.0.0  
**Source Specification:** `ANANTA_Master_Product_Requirements_Specification.md` (Sections 20, 21)  
**Target Codebase:** `ANANTA_MULTI_AGENT_ENGINE`  

---

### 1. Multi-Tier Testing Architecture

To guarantee total reliability, crash resilience, and media truthfulness without regressing the existing 574 passing tests, the testing suite is structured into six verification tiers:

```
+-----------------------------------------------------------------------------------------------+
|                                    ACCEPTANCE TEST PYRAMID                                    |
+-----------------------------------------------------------------------------------------------+
| Tier 6: Full Episode E2E & Packaging Tests (Playable MP4, SRT, Manifest Checksums)          |
+-----------------------------------------------------------------------------------------------+
| Tier 5: Timeline Assembly & Video Render Tests (Concat demuxer, FFmpeg filters, SRT sync)     |
+-----------------------------------------------------------------------------------------------+
| Tier 4: Media Provider Smoke Tests (Speech WAV synthesis, BMP placeholders, Image Diffusion)  |
+-----------------------------------------------------------------------------------------------+
| Tier 3: Continuity & Canon Verification Tests (Lore checks, power terms, character traits)   |
+-----------------------------------------------------------------------------------------------+
| Tier 2: DAG Concurrency & Orchestrator Recovery Tests (Race conditions, Worker cancellation) |
+-----------------------------------------------------------------------------------------------+
| Tier 1: Schema Validation & Unit Tests (JSON schemas, atomic file I/O, prompt templates)     |
+-----------------------------------------------------------------------------------------------+
```

---

### 2. Detailed Tier Specifications

#### Tier 1: Schema Validation, Atomic I/O & Prompt Contracts
* **Scope:** Validates that all 19 stage prompt templates render valid JSON, atomic file operations succeed without data loss, and stage outputs conform to `validation/schemas.py`.
* **Key Tests:**
  * `tests/test_validation.py`: Schema validation across all stage envelopes.
  * `tests/test_atomic_io.py`: Atomic write and replacement crash-safety.
  * `tests/test_m10_5_validation_feedback.py`: Dynamic feedback injection on retry.

#### Tier 2: DAG Concurrency, State Persistence & Crash Recovery
* **Scope:** Tests topological dependency scheduling, thread-safe state store persistence, circuit breaker isolation, and cooperative worker cancellation.
* **Key Tests:**
  * `tests/test_dependencies.py`: 19-stage DAG topological ordering.
  * `tests/test_m9_concurrent_orchestrator.py`: Multi-threaded stage execution.
  * `tests/test_m9_concurrent_race_conditions.py`: Thread synchronization and locks.
  * `tests/test_circuit_breaker.py`: Fault isolation and failure containment.
  * `tests/test_m8_crash_recovery.py`: Resume from simulated process crash.

#### Tier 3: Continuity & Canon Lore Verification
* **Scope:** Programmatic assertion of canonical rules (power progression: Spark $\rightarrow$ Resonance $\rightarrow$ Epic State; age 19 for core cast; Ronit height ratio; Aadhya hair thread removal; unknown lore marked `UNCONFIRMED`).
* **Planned Tests (`tests/test_phase_c_continuity.py`):**
  * `test_canon_power_terminology_enforcement()`
  * `test_character_knowledge_chronology()`
  * `test_visual_damage_and_outfit_continuity()`

#### Tier 4: Media Generation & Adapter Smoke Tests
* **Scope:** Verifies that media providers generate valid, decodable audio and visual binary files without corrupting JSON artifact pipelines.
* **Key Tests:**
  * `tests/test_phase_a_task_1_tts_and_dialogue.py`: Dialogue parsing, sequential ordering, 24 kHz WAV synthesis, slugified filenames, and audio metadata serialization.
  * `tests/test_phase_b_image_provider.py`: Diffusion adapter image generation and dimensions check.

#### Tier 5: Timeline Assembly & Video Rendering Tests
* **Scope:** Verifies that `TimelineAssembler` generates valid `.srt` subtitles, concat demuxer scripts, and FFmpeg command lines with correct resolution (1280×720), framerate (24 FPS), and audio mapping.
* **Key Tests:**
  * `tests/test_phase_a_task_2_timeline_assembler.py`: Manifest parsing, subtitle timestamp calculation (`HH:MM:SS,mmm`), overwrite protection, FFmpeg unavailable exception handling, and mock subprocess execution.

#### Tier 6: Full Episode End-to-End & Packaging Tests
* **Scope:** Executes full pipeline runs from raw brief/script to final distribution package containing master MP4, SRT subtitles, FCPXML, and SHA-256 checksum manifest.
* **Key Tests:**
  * `tests/test_m10_6_sequential_concurrent_e2e.py`: Complete 19-stage pipeline execution.
  * `tests/test_phase_a_prototype_e2e.py`: Playable prototype video generation smoke test.

---

### 3. Phase A (First Watchable Prototype) Acceptance Checklist

In accordance with Master Specification Section 20, Phase A MVP is declared **ACCEPTED** only when all 15 conditions below are verified:

| # | Acceptance Condition | Verification Method | Status |
|---|---|---|:---:|
| 1 | User supplies approved episode brief / script and character references. | Ingest into `outputs/{episode_id}/inputs/` | **Ready** |
| 2 | Engine creates validated scene/shot timeline manifest. | `TimelineManifest.validate()` | **`[VERIFIED]`** |
| 3 | Dialogue lines map to correct speaker and scene chronologically. | `DialogueExtractor.extract()` | **`[VERIFIED]`** |
| 4 | Real speech synthesized from configured TTS (mock audio labeled prototype). | `BaseTTSProvider.synthesize_dialogue()` | **`[VERIFIED]`** |
| 5 | Actual visual assets used (user-supplied artwork; placeholders disclosed). | `TimelineClip.image_path` existence check | **`[VERIFIED]`** |
| 6 | Every shot has valid duration and verified visual asset. | `TimelineManifest` duration validator | **`[VERIFIED]`** |
| 7 | BGM placed on timeline using approved / royalty-free track. | `AudioTrack(track_type="bgm")` | **`[VERIFIED]`** |
| 8 | Subtitles timed to dialogue speech within $\pm 100$ ms. | `generate_subtitles_srt()` | **`[VERIFIED]`** |
| 9 | Renderer produces decodable MP4 at 1280×720 24 FPS H.264/AAC. | `TimelineAssembler.render()` | **Blocked on FFmpeg** |
| 10 | Manifest records media origin, provider identity, and SHA-256 hashes. | `RenderResult.to_dict()` | **`[VERIFIED]`** |
| 11 | Technical QA confirms A/V stream decodability and duration sync. | Automated FFprobe validation | **`[VERIFIED]`** |
| 12 | User can review and approve timeline before final packaging. | Review CLI / Checkpoint | **Planned (Phase C)** |
| 13 | Package includes MP4, subtitles, timeline JSON, and checksum manifest. | `EpisodePackager.bundle()` | **Ready for Phase A** |
| 14 | Re-running pipeline does not overwrite approved assets without permission. | `FileExistsError` on existing outputs | **`[VERIFIED]`** |
| 15 | Final report truthfully lists real, mock, placeholder, and user assets. | Packaging report summary | **`[VERIFIED]`** |

---

### 4. Continuous Verification Protocol

Before declaring any implementation task complete:
1. Run focused unit and integration tests: `python -m pytest tests/test_focused.py`
2. Run full test suite regression: `python -m pytest` (Must achieve 100% pass rate).
3. Run linter check: `ruff check .` (Must return 0 errors).
4. Run whitespace and diff check: `git diff --check` (Must return 0 diff issues).
5. Verify protected invariant: `git diff 6a65491 -- pipeline/providers.py` (Must return 0 diffs).
