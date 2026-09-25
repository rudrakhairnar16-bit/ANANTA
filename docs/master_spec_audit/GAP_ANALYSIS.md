# Gap Analysis
## Technical, Architectural & Environmental Gaps vs. Master Specification

**Document Version:** 1.0.0  
**Source Specification:** `ANANTA_Master_Product_Requirements_Specification.md`  
**Target Codebase:** `ANANTA_MULTI_AGENT_ENGINE`  

---

### 1. Architectural & Subsystem Gaps

```
+-----------------------------------------------------------------------------------------------+
|                                  ARCHITECTURAL GAP SUMMARY                                    |
+------------------------------+------------------------------+---------------------------------+
| Architectural Subsystem      | Current State in Codebase    | Master Spec Target Requirement  |
+------------------------------+------------------------------+---------------------------------+
| 1. Binary Media Asset Store  | ArtifactStore (JSON only)    | AssetLibrary (Indexed files,    |
|                              | Media written ad-hoc         | hashes, versions, reverse refs) |
+------------------------------+------------------------------+---------------------------------+
| 2. Media Provider Hierarchy  | BaseProviderV2 (Text/LLM)    | BaseMediaProvider (Preflight,   |
|                              | BaseTTSProvider (Audio)      | seeds, cancel, binary bytes)    |
+------------------------------+------------------------------+---------------------------------+
| 3. Cross-Stage Continuity    | Prompts ask LLM to check     | ContinuityEngine (Deterministic |
|    Verification              | No programmatic engine       | rules, knowledge graph, checks) |
+------------------------------+------------------------------+---------------------------------+
| 4. Human-in-the-Loop (HITL)  | approval_status JSON string  | Interactive Review Gate Engine  |
|    Review & Pause Engine     | No pause/resume CLI gates    | (Pause DAG, diff, annotate, run)|
+------------------------------+------------------------------+---------------------------------+
| 5. Adobe Premiere Bridge     | Mock text block in schema    | Validated FCPXML 1.10 Generator |
|                              | Never tested in Premiere     | with absolute relink paths      |
+------------------------------+------------------------------+---------------------------------+
```

#### Gap 1.1: Binary Media Asset Store vs. JSON Artifact Store
* **Current State:** `pipeline/artifacts.py` manages JSON payload files (`outputs/artifacts/{episode_id}/{stage}_v{version}.json`). Binary media files (WAV, BMP, MP4) are generated directly into output subfolders without central indexing, checksum validation, deduplication, or MIME-type registration.
* **Target Requirement:** A dedicated `AssetLibrary` that stores, indexes, and tracks versions and SHA-256 hashes of all binary assets (images, audio stems, video clips, subtitles, turnarounds), with reverse-lookup capabilities (e.g. "which scenes use `prop_vel_astra_01`?").

#### Gap 1.2: Generalized Media Provider Contract
* **Current State:** `BaseProviderV2` is designed specifically for text-based LLM generation (prompt string $\rightarrow$ response text). `BaseTTSProvider` was introduced for speech synthesis, but there is no generalized `BaseMediaProvider` abstraction for Image Diffusion, Image-to-Video, Music, SFX, or Lip-Sync.
* **Target Requirement:** Standardized media provider interface featuring preflight capability probes, VRAM resource estimation, seed conditioning, cancelable worker threads, and binary output validation.

#### Gap 1.3: Programmatic Cross-Stage Continuity Engine
* **Current State:** Stage prompt templates instruct LLMs to maintain consistency, but there is no programmatic continuity checker. LLMs can hallucinate character knowledge, alter power states, or violate canon without detection.
* **Target Requirement:** A dedicated `ContinuityEngine` that validates:
  1. *Canon Facts:* Enforces immutable lore, power levels (Spark $\rightarrow$ Resonance $\rightarrow$ Epic State), and setting constraints.
  2. *Character State & Knowledge:* Verifies that characters only use information they have acquired up to the current scene.
  3. *Visual Identity:* Verifies that visual prompts reference approved turnaround IDs, maintain outfit damage across scenes, and adhere to fixed traits (e.g. Ronit ~150 cm height, Aadhya's hair thread removal).
  4. *Audio & Editorial:* Validates voice profiles, room tone ambience, and shot-to-shot spatial eyelines.

#### Gap 1.4: Interactive Human-in-the-Loop (HITL) Review Protocol
* **Current State:** Orchestrators execute all 19 stages straight through in automated batches.
* **Target Requirement:** Configurable review gates at critical milestones (Screenplay, Visual Keyframes, Voice Takes, Rough Cut, Final QA). When a gate is encountered, the orchestrator safely pauses, saves a checkpoint, alerts the operator via CLI or dashboard, allows revisions/annotations, and triggers selective downstream regeneration upon approval.

---

### 2. Stage-by-Stage Functional Gaps

| Stage ID | Stage Name | Current Implementation | Critical Functional Gap |
| :--- | :--- | :--- | :--- |
| **Stage 04** | `character` | LLM outputs character profiles JSON. | No integration with persistent character asset turnarounds, expression sheets, or voice profile IDs. |
| **Stage 05** | `world` | LLM outputs world/environment JSON. | No persistent location reference images, architectural rules, or lighting style guides. |
| **Stage 06** | `storyboard`| LLM outputs panel descriptions. | No visual keyframe panel image generation or reference-conditioned storyboard rendering. |
| **Stage 09** | `visual` | LLM outputs prompt strings. | **Major Gap:** No image generation adapter (ComfyUI / Stable Diffusion / Replicate API) to produce real PNG visual assets. |
| **Stage 10** | `motion` | LLM outputs animation style JSON. | **Major Gap:** No image-to-video diffusion adapter (SVD / AnimateDiff / API) or 2.5D parallax camera motion generator. |
| **Stage 11** | `voice` | Extracts dialogue & synthesizes mock WAVs. | Neural TTS adapter is structured but unverified against live installed models on the host machine. |
| **Stage 12** | `music` | LLM outputs score brief JSON. | No licensed audio catalog search, generative music provider, or audio file assignment. |
| **Stage 13** | `bgm` | LLM outputs cue list and ducking JSON. | No automatic audio ducking curves or stem placement on the physical timeline. |
| **Stage 14** | `sfx` | LLM outputs spot effects list JSON. | No local sound library search, environmental ambience layer, or audio file assignment. |
| **Stage 15** | `lipsync` | LLM outputs viseme schedule JSON. | **Major Gap:** No neural audio-to-viseme / face-warping model (Wav2Lip / SadTalker / LivePortrait). |
| **Stage 17** | `adobe_export`| LLM outputs synthetic XML string. | **Major Gap:** Does not produce valid FCPXML 1.10 with absolute media URIs verified to import into Adobe Premiere Pro. |
| **Stage 18** | `qa` | LLM outputs checks passed array. | No automated FFprobe media decodability, duration synchronization, or loudness verification. |
| **Stage 19** | `export` | LLM outputs deliverables list. | No automated packaging bundle creating a distribution ZIP with video, SRT, manifest, and checksums. |

---

### 3. Hardware, Tooling & Environment Gaps

#### Gap 3.1: Host FFmpeg Availability
* **Observation:** The host Windows environment does not currently have `ffmpeg` installed or accessible in system PATH (`ffmpeg -version` returned `CommandNotFoundException`).
* **Impact:** Physical MP4 video rendering cannot execute until FFmpeg is installed (e.g. via `winget install Gyan.FFmpeg`).
* **Resolution:** In accordance with guardrails, Antigravity has verified the command building and mock execution, but requires user permission to install FFmpeg or point to a local binary.

#### Gap 3.2: 6 GB VRAM Hardware Ceiling (NVIDIA RTX 3050 Laptop GPU)
* **Observation:** The target machine features an RTX 3050 with 6 GB VRAM and 2048 CUDA cores.
* **Impact:**
  * Cannot concurrently run Ollama (7B LLM ~4.5 GB VRAM) and heavy diffusion models (SDXL ~6.5 GB VRAM or SVD video ~12 GB VRAM).
  * Video diffusion models (Stable Video Diffusion, CogVideo) will trigger Out-Of-Memory (OOM) errors if run locally without aggressive quantization or offloading.
* **Resolution Strategy:**
  1. **Sequential Task Execution:** Unload Ollama from VRAM before invoking GPU-accelerated image generation.
  2. **Lightweight / Quantized Models:** Use SD 1.5 / SDXL Turbo / Flux.1-schnell (quantized) or CPU-based neural TTS (`Kokoro-82M`, `edge-tts`).
  3. **Cloud Offload Option:** Provide optional cloud adapter routing (Replicate / RunPod / fal.ai) for heavy video diffusion and lip-sync rendering.
