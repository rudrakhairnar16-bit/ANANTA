# Adobe Premiere Export Agent

**Purpose:** Convert approved production metadata into Adobe Premiere Pro import-ready files.

**Inputs:** screenplay, shot list, director notes, bgm plan, sound cues, voice/lipsync metadata.

**Outputs:** `adobe_import/` containing `edit_timeline.json`, `edit_timeline.csv`, `markers.csv`, and `README.md`.

**Rules:** This agent prepares an interchange package; it does not claim to control Adobe Premiere automatically. Actual project creation requires a configured Adobe extension/API or manual import.

**Quality gate:** Validate scene IDs, timecodes, asset paths, audio cues, and missing media before export.
