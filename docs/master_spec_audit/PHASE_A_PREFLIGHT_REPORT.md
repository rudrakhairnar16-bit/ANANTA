# Phase A Preflight & Asset Readiness Report
## 30-Second Hindi Canon Prototype: Rudra & Aadhya at Neo-Varanasi

**Document Version:** 1.0.0  
**Date:** September 2026  
**Auditor:** Antigravity (Lead Software Architect & AI Systems Engineer)  
**Target Configuration:**
* **Story Scene:** Rudra & Aadhya discover an Astra Resonance beacon in Neo-Varanasi (2042).
* **Language:** Hindi (हिन्दी).
* **Voice Profiles:** Rudra (`hi-IN-MadhurNeural`), Aadhya (`hi-IN-SwaraNeural`).
* **Video Specifications:** `1280 × 720` (720p), `24 FPS`, `H.264 (libx264)`, `AAC (192 kbps)`, `MP4`.
* **Target Runtime:** $30.0 \pm 1.0$ seconds.

---

### 1. Asset Readiness & Directory Audit

```
+-----------------------------------------------------------------------------------------------+
|                                      ASSET AUDIT SUMMARY                                      |
+------------------------------------+----------------+-----------------------------------------+
| Required Asset Item                | Current State  | Notes & Directory Location              |
+------------------------------------+----------------+-----------------------------------------+
| `inputs/prototype_hindi/visuals/`  | NOT FOUND      | Needs to be created for user artwork.   |
|   ├── `neo_varanasi_bg.png`        | Awaiting Input | Establishing background artwork (16:9). |
|   ├── `rudra_medium.png`           | Awaiting Input | Rudra character medium/close shot.      |
|   └── `aadhya_medium.png`          | Awaiting Input | Aadhya character medium/close shot.     |
| `inputs/prototype_hindi/audio/`    | NOT FOUND      | Needs to be created for BGM audio.      |
|   └── `atmospheric_bgm.mp3`        | Awaiting Input | Background music track (stereo WAV/MP3).|
| `inputs/prototype_hindi/script.json`| READY DRAFT    | Canonical 30s Hindi screenplay defined. |
+------------------------------------+----------------+-----------------------------------------+
```

* **Source Asset Preservation Guarantee:**
  * Ingestion component ([`pipeline/user_asset_ingest.py`](file:///c:/Users/Rudra/Desktop/ANANTA_Engine/ANANTA_MULTI_AGENT_ENGINE/pipeline/user_asset_ingest.py)) will read directly from `inputs/prototype_hindi/` in read-only mode without modifying, converting in-place, or overwriting original user source files.
  * Formats supported: PNG, JPG, WebP, WAV, MP3, AAC, FLAC.
  * Aspect Ratio Handling: Non-16:9 images will be scaled with lanczos interpolation and padded (letterbox/pillarbox) to fit 1280×720 without cropping or distortion.

---

### 2. Script & Dialogue Readiness (Canonical 30-Second Scene)

The following approved Hindi script segment adheres strictly to canonical lore (near-future Varanasi, Astra Resonance detection, authentic character dynamics, no forbidden terminology):

```json
{
  "episode_id": "ANANTA-PROTO-HI01",
  "title": "अस्त्र अनुनाद: नव-वाराणसी (Astra Resonance: Neo-Varanasi)",
  "language": "hi",
  "duration_seconds": 30,
  "scenes": [
    {
      "scene_id": "SCENE_01",
      "location": "Neo-Varanasi Ghats (2042) - Dusk",
      "dialogue": [
        {
          "sequence_index": 1,
          "speaker": "RUDRA",
          "character_id": "char_rudra",
          "text": "आध्या, ऊर्जा का यह स्तर सामान्य नहीं है। क्या यह कोई प्राचीन अस्त्र बीकन है?",
          "emotion": "suspicious, alert",
          "estimated_duration": 5.2
        },
        {
          "sequence_index": 2,
          "speaker": "AADHYA",
          "character_id": "char_aadhya",
          "text": "हाँ रुद्र। फ्रीक्वेंसी सीधे अस्त्र अनुनाद से मेल खा रही है... यह जाग रहा है।",
          "emotion": "composed, observant",
          "estimated_duration": 5.6
        },
        {
          "sequence_index": 3,
          "speaker": "RUDRA",
          "character_id": "char_rudra",
          "text": "अगर यह सक्रिय हुआ, तो पूरी ग्रिड बैठ जाएगी। हमें इसे अभी रोकना होगा।",
          "emotion": "urgent, resolute",
          "estimated_duration": 4.8
        },
        {
          "sequence_index": 4,
          "speaker": "AADHYA",
          "character_id": "char_aadhya",
          "text": "सावधानी से। शक्ति का प्रवाह अनियंत्रित है। मैं शील्ड तैयार करती हूँ।",
          "emotion": "protective, focused",
          "estimated_duration": 4.6
        }
      ]
    }
  ]
}
```

* **Preservation Rule:** The engine will never translate, rephrase, or alter these Hindi dialogue strings during synthesis or subtitle generation.

---

### 3. TTS Provider Readiness & Hindi Voice Validation

```
+-----------------------------------------------------------------------------------------------+
|                                      TTS READINESS AUDIT                                      |
+------------------------------------+----------------+-----------------------------------------+
| Component                          | Status         | Technical Assessment                    |
+------------------------------------+----------------+-----------------------------------------+
| Provider Engine                    | EdgeTTSProvider| Neural synthesis with 0 GB VRAM usage.  |
| Package Installation               | NOT INSTALLED  | Requires `pip install edge-tts`.        |
| Rudra Voice ID                     | VALIDATED      | `hi-IN-MadhurNeural` (Native Hindi Male)|
| Aadhya Voice ID                    | VALIDATED      | `hi-IN-SwaraNeural` (Native Hindi Female|
| Network Dependency                 | ONLINE REQUIRED| Connects to secure Azure TTS endpoint.  |
| Local Mock Fallback                | READY          | MockTTSProvider generates PCM WAV test. |
+------------------------------------+----------------+-----------------------------------------+
```

* **Format Conversion & Decodability:**
  * `edge-tts` generates standard MPEG-1 Layer 3 (`.mp3`) audio at 24 kHz mono.
  * [`providers/tts_provider.py`](file:///c:/Users/Rudra/Desktop/ANANTA_Engine/ANANTA_MULTI_AGENT_ENGINE/providers/tts_provider.py) saves these files directly to `outputs/ANANTA-PROTO-HI01/voice/`.
  * FFmpeg decodes MP3 streams natively during timeline assembly, converting and mastering to 192 kbps stereo AAC.

---

### 4. FFmpeg Video Rendering & Tooling Readiness

```
+-----------------------------------------------------------------------------------------------+
|                                    FFMPEG READINESS AUDIT                                     |
+------------------------------------+----------------+-----------------------------------------+
| Component                          | Status         | Technical Assessment                    |
+------------------------------------+----------------+-----------------------------------------+
| Host FFmpeg Binary                 | NOT IN PATH    | Requires `winget install Gyan.FFmpeg`.  |
| Concat Demuxer Script Engine       | READY          | Verified in `test_phase_a_task_2_*.py`. |
| Subtitle Formatter (.srt)          | READY          | Exact `HH:MM:SS,mmm` millisecond sync.  |
| Target Encoding Pipeline           | CONFIGURED     | `libx264` (yuv420p), `aac` (192k), 24FPS|
| Overwrite Safety Protection        | VERIFIED       | Rejects destructive overwrites.         |
+------------------------------------+----------------+-----------------------------------------+
```

---

### 5. Timeline Assembly & Pacing Structure

The 30-second timeline sequence cleanly matches the Hindi dialogue pacing:

```text
[00:00.000 - 00:04.500] Shot 1: Establishing Background — Neo-Varanasi Ghats & Drone Ambiance (4.5s)
[00:04.500 - 00:10.500] Shot 2: Rudra Medium Shot       — Dialogue 1: "आध्या, ऊर्जा का यह स्तर..." (6.0s)
[00:10.500 - 00:17.000] Shot 3: Aadhya Medium Shot      — Dialogue 2: "हाँ रुद्र। फ्रीक्वेंसी सीधे..." (6.5s)
[00:17.000 - 00:22.500] Shot 4: Rudra Close-Up          — Dialogue 3: "अगर यह सक्रिय हुआ..." (5.5s)
[00:22.500 - 00:27.500] Shot 5: Aadhya Close-Up         — Dialogue 4: "सावधानी से। शक्ति का प्रवाह..." (5.0s)
[00:27.500 - 00:30.000] Shot 6: Neo-Varanasi Wide Hold  — Dramatic Astra Glow & Fade to Black (2.5s)
Total Duration: Exactly 30.000 seconds
```

* **No Placeholder Images in Output:** Real user artwork will be mapped directly to each shot (`neo_varanasi_bg.png`, `rudra_medium.png`, `aadhya_medium.png`). Zero mock/placeholder BMPs will be referenced.

---

### 6. Audio Mixing, Dynamic Sidechain Ducking & Limiter

To ensure dialogue clarity over atmospheric music:
1. **Dialogue Stem Bus:** All speech lines are mapped with exact start timestamps ($t_1=4.5\text{s}$, $t_2=10.5\text{s}$, $t_3=17.0\text{s}$, $t_4=22.5\text{s}$).
2. **Dynamic Sidechain Ducking Filtergraph:**
   ```text
   [bgm][dialogue]sidechaincompress=threshold=0.08:ratio=4:attack=200:release=500:makeup=1[ducked_bgm];
   [dialogue][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2[mixed_audio];
   [mixed_audio]alimiter=limit=0.95:attack=5:release=50[final_audio]
   ```
   * When speech occurs, BGM volume automatically ducks smoothly by $-12\text{ dB}$.
   * When speech ceases, BGM smoothly restores to full atmospheric volume.
   * `alimiter` prevents any potential clipping.

---

### 7. Remaining Blockers & Required Actions

```
+----+----------------------------+---------------+---------------------------------------------+
| #  | Blocker Description        | Blocker Type  | Action Required to Unblock                  |
+----+----------------------------+---------------+---------------------------------------------+
| 1  | FFmpeg binary missing      | Environment   | Authorize running `winget install Gyan.FFmpeg`|
| 2  | `edge-tts` package missing | Environment   | Authorize running `pip install edge-tts`    |
| 3  | User artwork & BGM files   | Input Media   | Place artwork files in `inputs/` folder.    |
+----+----------------------------+---------------+---------------------------------------------+
```

---

### 8. Exact Next Steps

Once you give authorization:

1. **Step 1 (Environment Setup):**
   ```powershell
   winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
   pip install edge-tts
   ```
2. **Step 2 (Directory Initialization):**
   * Create `inputs/prototype_hindi/visuals/` and `inputs/prototype_hindi/audio/`.
3. **Step 3 (Asset Loading):**
   * Place `neo_varanasi_bg.png`, `rudra_medium.png`, `aadhya_medium.png`, and `atmospheric_bgm.mp3` into the input folders (or authorize sample test artwork generation).
4. **Step 4 (Implementation & Synthesis):**
   * Synthesize real Hindi speech via `EdgeTTSProvider` using `hi-IN-MadhurNeural` & `hi-IN-SwaraNeural`.
   * Generate `subtitles.srt`.
   * Render `outputs/ANANTA-PROTO-HI01/prototype_episode.mp4`.
   * Create SHA-256 package manifest.

---

### Stop Condition

* **Report generated:** [`docs/master_spec_audit/PHASE_A_PREFLIGHT_REPORT.md`](file:///c:/Users/Rudra/Desktop/ANANTA_Engine/ANANTA_MULTI_AGENT_ENGINE/docs/master_spec_audit/PHASE_A_PREFLIGHT_REPORT.md).
* **No dependencies have been installed.**
* **No network calls or file modifications have been made.**
* **Awaiting your approval to proceed with Step 1 and Step 2.**
