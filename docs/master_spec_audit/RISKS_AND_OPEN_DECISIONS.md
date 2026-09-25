# Risks & Open Decisions
## Risk Register, Mitigation Strategies & Decisions Required for ANANTA Engine

**Document Version:** 1.0.0  
**Source Specification:** `ANANTA_Master_Product_Requirements_Specification.md` (Sections 16, 17, 23)  
**Target Codebase:** `ANANTA_MULTI_AGENT_ENGINE`  

---

### 1. Comprehensive Production Risk Register

```
+-------------------------------------------------------------------------------------------------------+
|                                         PRODUCTION RISK MATRIX                                        |
+----+----------------------------+----------+--------+-------------------------------------------------+
| ID | Risk Description           | Severity | Likeli | Mitigation Strategy                             |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R1 | 6 GB VRAM Exhaustion (OOM) | HIGH     | HIGH   | Strict sequential scheduling; unload Ollama LLM |
|    | when running Image/Video   |          |        | before launching Diffusion/TTS; offload heavy   |
|    | models on RTX 3050.        |          |        | video rendering to cloud or lightweight CPU.   |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R2 | Host FFmpeg Missing        | HIGH     | HIGH   | Fail clearly with FFmpegUnavailableError;       |
|    | blocking physical MP4      |          |        | obtain owner approval to install FFmpeg via     |
|    | rendering.                 |          |        | 'winget install Gyan.FFmpeg'.                   |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R3 | Character Visual Drift     | HIGH     | MED    | Use reference-conditioned generation (IP-       |
|    | across sequential shots.   |          |        | Adapter / ControlNet) with fixed character seed |
|    |                            |          |        | and approved turnaround sheets; HITL approval.  |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R4 | Canon Lore Hallucination   | MED      | MED    | Programmatic ContinuityEngine enforcing lore    |
|    | (e.g. power term regression|          |        | rules and terminology dictionary at QA stage.   |
|    | to "Avatar State").        |          |        |                                                 |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R5 | Audio/Subtitle Drift       | MED      | MED    | Probe physical audio file durations via wave/   |
|    | causing desynchronization. |          |        | ffprobe and snap subtitle timestamps to speech. |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R6 | Premiere FCPXML Media      | MED      | MED    | Use absolute file:/// URIs, POSIX path slashes, |
|    | Offline Import Errors.     |          |        | and test interchange with active Premiere Pro.  |
+----+----------------------------+----------+--------+-------------------------------------------------+
| R7 | Unintended Cost Overrun    | HIGH     | LOW    | Guardrail: Zero paid API calls without explicit |
|    | on Cloud API Endpoints.    |          |        | per-call or per-phase owner approval & budgets. |
+----+----------------------------+----------+--------+-------------------------------------------------+
```

---

### 2. Deep-Dive Risk Analysis & Mitigations

#### Risk R1: GPU VRAM Exhaustion & Thermal Throttling
* **Context:** The development laptop GPU is an NVIDIA RTX 3050 Laptop GPU with 6 GB GDDR6 VRAM.
* **Risk:** Running local 7B LLMs (e.g., Llama 3.1 in Ollama ~4.5 GB VRAM) simultaneously with Stable Diffusion (6–8 GB) or video diffusion models (12+ GB) causes immediate CUDA OOM crashes or severe system thrashing.
* **Mitigation Strategy:**
  1. *Resource Lifecycle Manager:* Implement automated pre-execution hooks to unload LLMs from VRAM before invoking GPU-accelerated image synthesis.
  2. *Lightweight Local Encoders:* Standardize on quantized image diffusion (SD 1.5 with ControlNet or SDXL-Turbo) and CPU-based neural speech synthesis (`edge-tts` or `Kokoro-82M`).
  3. *Optional Cloud Offloading:* Offer opt-in cloud provider adapters (Replicate / RunPod) for heavy video diffusion tasks.

#### Risk R2: Missing FFmpeg Binary on Development Host
* **Context:** `ffmpeg` is not currently recognized in the host PowerShell PATH.
* **Risk:** Video timeline assembly cannot render real MP4 container files or encode AAC audio on the local filesystem.
* **Mitigation Strategy:**
  * In Phase A, Antigravity has isolated FFmpeg execution behind `TimelineAssembler.render()`, which detects availability and raises `FFmpegUnavailableError` with explicit installation guidance.
  * Antigravity requests formal user authorization to run `winget install Gyan.FFmpeg` to install FFmpeg natively.

#### Risk R3: Character Visual Inconsistency & Hallucinations
* **Context:** Generative diffusion models without reference conditioning produce varying faces, costumes, and color palettes across scenes.
* **Risk:** Rudra, Aadhya, Ronit, and Ira may look visibly different in every keyframe.
* **Mitigation Strategy:**
  * Mandate approved character turnaround reference sheets in `AssetLibrary`.
  * Condition image prompts using ControlNet openpose, reference-only, or IP-Adapter embeddings.
  * Introduce an interactive Human Review Gate after Stage 6 (Storyboard) / Stage 9 (Visual) allowing the operator to approve or re-roll keyframes before motion generation.

---

### 3. Decisions Required from Project Owner

In accordance with Master Specification Section 23, the following decisions are formally submitted to the project lead/owner for direction before Phase A/B implementation:

| Decision # | Topic | Available Options | Recommended Default | Impact / Rationale |
| :---: | :--- | :--- | :--- | :--- |
| **DEC-01** | **Host FFmpeg Installation** | A) Install via `winget install Gyan.FFmpeg`<br>B) Point to existing manual binary path<br>C) Test with mock commands only | **Option A (Recommended)** | Required to render real MP4 prototype video files locally. |
| **DEC-02** | **Phase A MVP Video Target** | A) 30-second single-scene prototype<br>B) 60-second multi-scene teaser<br>C) Full 2-minute scene sequence | **Option A (Recommended)** | Shortest practical path to validating the complete end-to-end media pipeline. |
| **DEC-03** | **Production TTS Provider** | A) `EdgeTTS` (Free, high-quality neural voices)<br>B) `Kokoro-82M` (Free, local CPU/GPU neural TTS)<br>C) User-recorded audio WAV files<br>D) Paid Cloud TTS (ElevenLabs) | **Option A (Recommended for MVP)** | `EdgeTTS` provides immediate natural anime voice quality with zero GPU VRAM consumption. |
| **DEC-04** | **Visual Asset Strategy for MVP** | A) User-supplied character/background images<br>B) Local Stable Diffusion generation<br>C) Cloud Diffusion API (Replicate / fal.ai) | **Option A (Recommended for Phase A)** | Eliminates visual drift risk during initial pipeline and timeline assembly verification. |
| **DEC-05** | **BGM & Sound Sourcing** | A) User-supplied royalty-free / licensed WAVs<br>B) Local AudioCraft / MusicGen generation<br>C) Cloud Generative Audio API | **Option A (Recommended)** | Guarantees high-quality, reproducible audio mixing without VRAM exhaustion. |
| **DEC-06** | **Review Gate Policy** | A) Pause at Screenplay, Storyboard, and Rough Cut<br>B) Pause only before Final Master Export<br>C) Fully automated continuous run | **Option A (Recommended)** | Prevents downstream wasted computation on flawed story or visual assets. |
| **DEC-07** | **Target Master Video Profile** | A) 1280×720 (720p), 24 FPS, H.264/AAC<br>B) 1920×1080 (1080p), 24 FPS, H.264/AAC | **Option A (720p for MVP)** | Minimizes rendering latency and storage footprint while maintaining broadcast proportions. |
| **DEC-08** | **Adobe Premiere Target Version** | A) FCPXML 1.10 (Premiere Pro 2023+)<br>B) Premiere Project XML (Classic FCP 7 XML) | **Option A (Recommended)** | Broadest modern NLE compatibility and clean track structure. |
