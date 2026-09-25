# ANANTA Engine --- Master Product Requirements & Production System Specification

**Purpose:** Canonical product-level reference for Antigravity to audit,
plan, implement, test, and validate an end-to-end ANANTA anime
production engine.\
**Status:** Working master specification. Repository-specific facts must
be verified before implementation.

## Instructions to Antigravity

Treat this document as the target product specification, not proof that
features already exist. First inspect the repository, current PRD,
schemas, stage implementations, providers, tests, production status, and
git state. Map every requirement to `implemented`, `partial`, `missing`,
or `blocked`, with evidence and file paths. Do not blindly rewrite the
repository or silently resolve conflicts with approved canon.

Implement incrementally in testable vertical slices. Preserve working
architecture/contracts when practical. Never claim a real image, voice,
music, video, lip-sync, continuity check, or final render unless it was
actually produced and validated. Label mock, placeholder, synthetic,
user-supplied, and real-generated media accurately. Fail clearly for
missing providers/tools/models. Do not overwrite source/approved assets
by default. No paid services, large model downloads, installs, commits,
pushes, destructive changes, or canon edits without owner approval. Keep
secrets out of code and logs.

## 1. Product vision

ANANTA Engine is a modular, AI-assisted anime production system. The
user supplies approved story material, episode briefs/scripts,
character/world references, visual/audio preferences, and feedback.
Agents transform approved inputs into structured plans, generated media,
edited timelines, QA reports, and a final episode package.

**Target flow:** Canon/project bible → episode brief → screenplay →
scene/shot breakdown → approved assets → images/keyframes → motion/video
→ dialogue/voice → music/BGM/SFX → lip-sync → edit/timeline → QA/review
→ final render/export/package.

Support both human-directed production and controlled automation. The
first goal is one short, watchable, end-to-end episode/prototype. Expand
only after that vertical slice works.

Principles: canon first; human creative control; character/asset
consistency; provider independence; truthful media labels;
reproducibility; hardware/cost awareness; incremental delivery.

## 2. Protected ANANTA canon

These are known project facts. If a newer explicitly approved canon
source conflicts, flag the discrepancy and ask the owner; do not
silently replace either source.

-   Title: **ANANTA**. Tagline: **"The Gods Remember. Humanity
    Forgets."**
-   Genre: action, supernatural, sci-fi thriller, fantasy. Setting:
    near-future India; 2042 is tentative.
-   Premise: reincarnated divine beings, Astra Resonance, cosmic cycles
    inspired by Hindu mythology. Central uncertainty: "Gods return, but
    nobody knows whether they came to save humanity or judge it."
-   Adventure is primary; relationships/chemistry may exist but romance
    is not the main focus.
-   Intended path: written chapter/book foundation first, then
    AI-assisted video/YouTube. Long-term episode target discussed:
    25--30 minutes. MVP may be shorter if clearly labeled as a
    pilot/prototype.
-   Power progression: **Spark → Resonance → Epic State**. Do not revert
    to "Avatar State."
-   Rudra's Epic State: **Unbound** (name status should follow latest
    canon); themes include destruction, transformation, chaos, breaking
    limits.
-   Aadhya's Epic State: **Shakti**; respectful fictional themes of
    creation, preservation, restoration, life-force, nature, adaptation,
    balance, renewal. She is not merely a love interest or calming
    device.
-   Core team members are all **19**: Rudra, Aadhya, Ronit, Ira.
-   Rudra: sarcastic/funny/confident-looking, sometimes careless; may
    want to leave immediately after missions. Backstory includes
    abusive/toxic alcoholic father and protective supportive mother.
    Ronit and Ira know his history first; Aadhya initially sees his
    outer persona. Preserve approved reference image/design.
-   Aadhya: nature-linked creative/adaptive/restorative counterpart.
    Preserve approved design; a previously requested blue thread coming
    from her hair was to be removed.
-   Ronit: height around 150 cm per design request; Kartikeya-inspired
    warrior, not a direct divine depiction/reincarnation claim. Sena
    Astra Resonance, Vel Astra spear, Epic State Velum; discipline,
    protection, coordination, kinetic precision, Sena Mandala formation.
    Arc: from protecting everyone alone to trusting the team.
    Brother-like bond with Rudra; comes from a well-settled warrior/army
    family.
-   Ira: orphan, knows Rudra and Ronit since school;
    researcher/truth-holder investigating Astra Resonance, Divine Cycle,
    hidden connections.

These notes are not permission to invent missing plot facts. Retrieve
full approved character sheets, scripts, references, and canon from
user-approved files. Mark unknowns `UNCONFIRMED`.

## 3. Scope

### In scope

Project/series bible and canon management; episode brief, screenplay,
scene/shot breakdown, storyboard, directing/camera/motion plans;
character/world/location/prop asset library; reference-image
consistency; image and image-to-video providers; dialogue extraction,
voice casting, TTS/recording, voice profiles; music/BGM/SFX/ambience and
timing/mixing/ducking; lip-sync/visemes where supported; timeline
assembly, subtitles, render/export; human approval, feedback,
versioning, retries, pause/resume; continuity and technical QA; episode
packaging, manifests, checksums, logs and lineage.

### Out of scope unless approved

Autonomous social publishing; unapproved paid APIs/subscriptions; custom
foundation-model training as a default; unapproved canon/design changes;
promises of perfect consistency/lip-sync; hands-off production before
review and reliability gates are proven.

## 4. Media origin and lifecycle labels

Every run/asset must distinguish: - `mock`: deterministic test-only
output. - `placeholder`: temporary stand-in, visibly labeled. -
`synthetic`: generated by a provider but not human-approved. -
`real_generated`: actual output from a configured provider, with
provider identity. - `user_supplied`: uploaded by the user. -
`approved`: human-reviewed state, independent of origin. - Lifecycle
states: `draft`, `pending_review`, `approved`, `rejected`, `superseded`,
`failed`, `blocked`, `stale`.

Mock/placeholder assets must never be presented as final anime. A
prototype built with mock tones or placeholder visuals must be labeled
technical prototype.

## 5. Target architecture

Preserve the current 19-stage conceptual pipeline where useful, but
separate: 1. Project/canon store. 2. Orchestrator: DAG scheduling,
sequential/concurrent execution, checkpoints, pause/resume,
cancellation, idempotency. 3. Agent layer: structured planning with
schema validation and prompt/template versions. 4. Provider adapters:
LLM, image, TTS, music/SFX, video/motion, lip-sync, storage, renderer.
5. Asset manager: IDs, files, metadata, hashes, versions, references,
approvals and lineage. 6. Continuity engine: canon retrieval,
contradiction checks, character/world/time/location/prop continuity,
visual/audio identity constraints. 7. Timeline/renderer: manifest, media
probing, clip order, audio mix, subtitles, render jobs. 8. QA/review:
automated checks and human gates. 9. Delivery/package: master render,
project files, subtitles, manifests, checksums and reports. 10.
Observability/config: logs, progress, metrics, provider status, resource
use and cost estimates.

LLM agents produce plans/prompts, not pretend to create binary media.
Media providers generate actual bytes. Asset manager validates and
versions them. Timeline assembler consumes verified media. QA checks
actual files. Human review controls canon-sensitive or costly steps.

### Provider adapter contract

Capability/provider ID/type; health/preflight;
dependencies/credentials/models; input/output schema; timeouts and
cancellation; resource/cost estimates where available; retryable errors;
output validation and metadata; privacy/network behavior; explicit
mock/real labels. Use a dedicated media-provider contract if the
existing text-oriented provider base is unsuitable. Do not push binary
files into JSON artifacts.

## 6. Responsibilities of the 19 conceptual stages

Verify exact IDs/schema names in the repository; these are target
responsibilities.

1.  **story:** concept, synopsis, acts, beats, canon references.
2.  **screenplay:** scenes, action, dialogue, speaker IDs, emotional
    intent, duration estimates.
3.  **scene_plan:** shot breakdown, IDs, durations, framing,
    visual/audio needs, asset references.
4.  **character:** canon-linked profiles, character states, reference
    sheets, voice profile IDs.
5.  **world:** environment rules, geography, time/weather, palette,
    props and constraints.
6.  **storyboard:** ordered panels/keyframes, framing, poses, image
    prompts and reference assets.
7.  **director:** visual language, pacing, performance and scene
    direction.
8.  **camera:** shot size, lens/look, movement, lighting, composition
    and motion instructions.
9.  **visual:** actual image generation and files, not only prompts.
10. **motion:** actual video/2.5D animation clips and metadata.
11. **voice:** dialogue extraction, casting, TTS/recording, actual audio
    and timing.
12. **music:** score brief, themes, cues, music asset
    generation/selection.
13. **bgm:** cue placement, time ranges, transitions, volume automation
    and ducking.
14. **sfx:** effects spotting, ambience, asset lookup/generation and
    timing.
15. **lipsync:** audio-to-viseme/face mapping where supported, with
    confidence/provider metadata.
16. **edit:** timeline manifest, clip arrangement, transitions and
    synchronization.
17. **adobe_export:** valid interchange file referencing real media;
    test actual import.
18. **qa:** canon/continuity, completeness, media, sync, subtitle,
    render and human review.
19. **export:** master encode, variants, subtitles, project assets,
    manifests, checksums and report.

Every stage defines inputs, outputs, schema, capability/provider,
dependencies, failure/retry behavior, lineage, approval requirement and
acceptance tests.

## 7. Continuity system --- critical, cross-cutting

Continuity must run throughout planning, generation, editing and final
QA---not just at the end.

### Story/canon continuity

Track confirmed canon facts and source citations; chronology, dates,
elapsed time, flashbacks, cause/effect; each character's knowledge state
and secrets; goals, relationships, injuries, power progression, emotions
and dialogue voice; world rules, Astra Resonance/power limits,
locations/travel, technology/factions; names, glossary and terminology;
deliberate mysteries.

Checks: no unapproved canon contradiction; no character uses knowledge
they have not acquired; no impossible chronology/location jump; no
unapproved change to age/design/powers/backstory; preserve intentional
ambiguity. Never "resolve" a mystery automatically.

### Visual continuity

Track stable IDs/references for face/body/design,
clothing/accessories/colors/silhouette/hair; scene state (outfit,
damage, dirt, emotion, power effects); location layout, time, weather,
lighting/palette; props/weapons and their ownership/position/state;
shot-to-shot screen direction, eyelines, spatial positions; visual
style, line weight, rendering, aspect ratio and color treatment.

Each image/clip records character/location/prop IDs and reference IDs,
prompt/negative prompt where supported, provider/model/version,
seed/settings where available, source keyframe IDs, applied constraints,
checks and approval status. Do not promise perfect consistency; use
reference-conditioned generation and human selection when uncertain.

### Audio continuity

Track stable character voice ID, language/accent, pitch/style/rate;
dialogue text version, speaker, scene/shot/line index, emotion,
pronunciation, retakes; room tone/ambience; music
motifs/cues/intensity/tempo/start/end/transitions; SFX
identity/timing/perspective;
loudness/clipping/silence/channel/sample-rate; voice consistency and
approval.

### Editorial continuity

Track shot order/durations, transitions, screen direction, match cuts,
eyelines, action continuity, dialogue/subtitle timing, BGM/SFX placement
and fades, frame rate/timebase/aspect ratio/color/audio format,
immutable timeline asset versions.

### Continuity report

Each finding includes check ID/category/severity, affected
scene/shot/asset, expected rule vs observed value, evidence/source IDs,
confidence, automated vs human confirmation, suggested correction,
status (`pass`, `warning`, `fail`, `needs-review`, `waived`), reviewer,
waiver reason, timestamp and version. Canon-sensitive corrections
require human approval.

## 8. Character/world bible and asset library

Stable IDs: `character_id`, `location_id`, `prop_id`, `costume_id`,
`voice_profile_id`, `style_profile_id`, `asset_id`, `asset_version`,
`episode_id`, `scene_id`, `shot_id`, `dialogue_id`, `cue_id`. Do not use
display names/filenames as identity.

Character profile: canonical
name/aliases/age/role/personality/goals/backstory/relationships/knowledge
state; approved references (turnarounds, expressions, full body, outfit
variants where available); fixed design traits/prohibited changes;
costumes/accessories/props and valid conditions; voice
profile/language/pronunciation/emotional range; power state/effects;
first appearance, chronology, source citations and approval.

Asset library: user uploads, references, scripts, images, audio, logos,
backgrounds and props;
metadata/tags/dimensions/duration/format/hash/lineage/version;
previews/contact sheets; approval states; reverse usage lookup; safe
import/deduplication/path validation/missing-file detection.

## 9. Dialogue, voice, BGM, music and SFX

### Dialogue record

Unique dialogue ID, scene/shot, order, character/speaker ID, exact
approved text, language, emotion/delivery, pronunciation notes,
estimated/actual duration, pause markers, retake/version, subtitle
text/timing and approval. Do not call mock tone audio spoken dialogue.

### TTS/recording

Adapters for local/cloud TTS and user recordings; stable per-character
voice mapping; pronunciation dictionary; batch/rate limits/resumable
jobs; format conversion only with verified tools; validate decodability,
duration, sample rate/channels and non-empty output; preserve takes as
versions; store alignment if available, otherwise mark timing estimated.

### Music/BGM

Separate score brief from actual asset generation/selection. Each cue
has cue ID, scene/shot range, start/end,
motif/mood/intensity/tempo/instrumentation, transition/fade, track
file/version/provider/origin, rights note if known, mix
level/ducking/loop/crossfade and placeholder/approved status. Use
user-supplied/licensed assets or an approved provider. Do not claim
rights not verified.

### SFX/ambience

Spot effects per action/scene; search library before generation; record
source, distance, environment, timing, gain/pan/spatial metadata;
maintain ambience across cuts; check missing/duplicate/unintended loud
effects.

### Final mix

Dialogue intelligibility and ducking; BGM/SFX fades;
peak/clipping/loudness checks; A/V duration alignment; configurable
delivery profiles; separate stems where practical: dialogue, music, SFX,
ambience, final mix.

## 10. Visual, motion and video

Image generation adapter: health/timeouts/retry/cost/resource; prompt
from shot direction + canon + reference assets; preserve
aspect/style/reference IDs/seed/settings where available; save actual
bytes; validate format/dimensions/readability; require human selection
before expensive motion when configured.

Motion capability ladder: 1. Still image timeline with pan/zoom/crop for
MVP. 2. 2.5D/parallax where assets support it. 3. Image-to-video
provider for selected shots. 4. Advanced animation/lip-sync after stable
inputs/review.

Every clip records source image IDs, duration/FPS/resolution,
provider/model, motion prompt, settings/seed, output validation. Visual
QA: missing/black/corrupt frames, dimensions/aspect/FPS, order/duration,
reference/style checks with confidence, flicker/continuity warnings
where feasible, placeholder disclosure.

## 11. Timeline, editing and rendering

### Timeline manifest

Versioned source of truth: project/episode/timeline version;
FPS/timebase/resolution/aspect; ordered scenes/shots/start/end/duration;
immutable asset IDs/versions for
visuals/dialogue/BGM/SFX/ambience/subtitles;
transitions/crop/scale/position/effects; audio gain/pan/fades/ducking;
subtitle timing; track type/order/mute/solo; render profile; origin
labels and validation.

### Renderer

Use FFmpeg or another explicitly chosen renderer. Probe inputs; reject
corrupt/unsupported media; deterministic order and duration/timebase;
cancellation/progress where feasible; render to temp, validate, then
atomically publish; do not mark complete until output decodes and meets
profile; preserve logs/commands while redacting secrets.

### Adobe bridge

Generate FCPXML or another supported interchange only after testing
against actual target. Link real media paths, validate path
resolution/relink metadata. Do not claim Premiere compatibility until
import is tested.

## 12. Human review and feedback

Configurable gates: 1. Canon/brief. 2. Screenplay. 3.
Character/world/visual references. 4. Storyboard/keyframes. 5. Voice
casting/dialogue audio. 6. Music/SFX. 7. Rough cut. 8. Final QA/master
export.

Actions: approve, reject, request revision, annotate, compare versions,
lock canon/assets, waive with reason. Feedback attaches to
stage/artifact/scene/shot/line/asset IDs. Regenerate only affected
descendants where possible. Preserve rejected versions. Costly
generation requires configured approval/budget policy.

## 13. Dependency tracking and selective regeneration

Every output records input artifact IDs/versions. Upstream changes mark
descendants `stale`; they must not silently reuse stale outputs. Offer
selective regeneration; preserve approved assets unless explicitly
unlocked; compare versions and summarize changes; rerun relevant
continuity and technical QA. Distinguish hard dependencies, soft
references, approval gates and optional branches.

## 14. QA and release gates

### Stage QA

Schema validity; input provenance/canon references; provider and
mock/fallback labels; output file
existence/format/hash/size/decodability; retries/failure state/no false
publication; prompt/model/config version traceability.

### Episode QA

Required shots/assets present; no missing media links; no critical
continuity failures; dialogue/subtitles aligned within configured
tolerance; BGM/SFX do not mask dialogue; A/V duration/timebase
agreement; render decodes and meets profile; mock/placeholder
disclosure; approvals satisfied; package manifest/checksums complete.

### Release states

`DRAFT → PLANNED → GENERATING → REVIEW_REQUIRED → APPROVED_FOR_RENDER → RENDERING → QA_REQUIRED → APPROVED → PACKAGED`
Side states: `BLOCKED`, `FAILED`, `CANCELLED`, `STALE`, `REJECTED`. A
technical prototype remains labeled prototype; only validated/approved
render may be called final.

## 15. Persistence, recovery and observability

Durable run/stage IDs; checkpoint/resume; idempotency keys; retry only
transient failures; cancellation propagation; progress per
stage/job/render; structured logs/correlation IDs/secrets redaction;
provider health/latency/retries/failures/bytes/duration/storage/cost;
concurrency/GPU/CPU/disk/network guardrails; cleanup only for
unreferenced temporary files under an explicit retention policy.

## 16. Security, rights and storage

Secrets in environment/secure config, never committed. Respect provider
terms, content rights, voice/image consent and licensing. Preserve
source assets. Record rights/origin status; unknown remains unknown.
Path validation/safe filenames/no traversal. Show external data transfer
and support local-only mode. Separate project
data/cache/temp/deliverables; configurable cache retention; avoid
sensitive logs.

## 17. Hardware/deployment constraints

Known environment: Windows, RTX 3050 Laptop GPU 6 GB VRAM, Ollama, Adobe
Premium, limited storage and heat concerns. Prefer local LLM/lightweight
CPU TTS where practical; do not assume high-end local video generation.
Schedule GPU-heavy tasks sequentially/configurable; local/cloud/hybrid
choices; cloud opt-in with costs/credentials; mock mode explicit for
tests; detect missing FFmpeg/models/tools; no automatic large model
downloads.

## 18. Data contracts and provenance

Each stage/artifact includes as applicable:
project/episode/stage/run/artifact IDs and version; input artifact
IDs/versions; provider/type/model/version/fallback/origin;
prompt/template/schema version; seed/settings;
timestamp/duration/size/hash; validation/warnings/errors;
approval/reviewer; canon sources and asset IDs;
MIME/format/dimensions/duration/sample rate. Keep media bytes as files
and JSON as references/metadata.

## 19. Roadmap and phase acceptance

### Phase 0 --- Audit/alignment

Gap map, architecture, requirements traceability matrix, approved phase
plan. Exit: repository reality and assumptions are explicit.

### Phase A --- Minimum complete episode vertical slice

One short, clearly labeled prototype from approved brief to playable
MP4: 1. Dialogue extraction/TTS. 2. Timeline manifest/FFmpeg assembler.
3. Real images (user-supplied or configured provider; placeholders only
in tests). 4. Real dialogue audio or user recordings. 5. Basic BGM/SFX
using user-supplied/licensed assets. 6. Subtitles, timing, assembly,
render validation. 7. Basic review gate and package manifest. Exit:
actual playable short MP4 with linked assets, accurate origin labels,
sync, subtitles, report. Mock/placeholder media means prototype-only
exit.

### Phase B --- Real media generation

Image adapter/reference-conditioned generation, asset library, voice
profiles/retakes, music/SFX provider/catalog, motion provider. Exit:
real media generated, traced, previewed and reusable.

### Phase C --- Continuity/review/Adobe

Canon retrieval/checks, identity tracking, approval/revision/selective
regeneration, validated Premiere interchange. Exit: reviewable rough cut
and traceable continuity findings.

### Phase D --- Lip-sync/advanced motion/full integration

Lip-sync, selected video-generation adapters, multi-track mix, advanced
edit, media QA, all 19 stages connected to real media where applicable.
Exit: repeatable reviewable episode package.

### Phase E --- Scale/UX

Multi-episode queue, dashboard, batch processing,
monitoring/cost/resource tracking, review UI/export profiles. Exit:
scalable production without losing canon/provenance/review control.

## 20. First watchable prototype --- acceptance checklist

Complete only when: 1. User supplies approved brief/script and character
references. 2. Engine creates validated scene/shot timeline. 3. Dialogue
lines map to correct speaker/scene. 4. Real speech from configured TTS
or user recordings; mock tones do not qualify. 5. Actual
user-supplied/generated visuals; no unlabeled placeholders. 6. Every
shot has valid duration and visual asset. 7. BGM/optional SFX placed
using approved/user-supplied/licensed assets. 8. Subtitles timed to
dialogue/audio. 9. Renderer produces decodable MP4 at chosen profile.
10. Manifest records media origin/provider/version/approval. 11.
Continuity and technical QA have no unresolved critical issues. 12. User
can review/approve before packaging. 13. Package includes MP4,
subtitles, timeline, asset manifest, QA/continuity report and logs. 14.
Reruns do not overwrite approved assets or silently duplicate outputs.
15. Report truthfully lists real, mock, placeholder and manually
supplied components.

## 21. Antigravity execution protocol

After owner approval: 1. Build requirements traceability matrix mapping
requirement → existing code → gap → task → test. 2. Break phases into
small tasks with dependencies and acceptance criteria. 3. For each task:
inspect → tests first → minimal implementation → focused/regression
tests → lint/diff → report. 4. No unrelated bundled changes. 5. After
each task, stop and report files, behavior, exact test results,
real-media smoke-test status, limitations and next task. 6. Do not
declare a phase complete without demonstrating actual media and
validation. 7. Do not self-approve paid API usage, model downloads,
commits, pushes, destructive operations or canon changes.

## 22. Immediate next actions

1.  Audit Phase A Task 1 TTS and Task 2 assembler against this spec.
2.  Confirm FFmpeg availability and request owner approval for
    installation if needed.
3.  Create Phase A traceability matrix.
4.  Add a real image-input path using user-supplied images first.
5.  Configure real TTS only after owner chooses provider.
6.  Add basic BGM using user-supplied/licensed track.
7.  Render and validate a short end-to-end prototype.
8.  Then expand to image generation, advanced motion, lip-sync and full
    continuity.

## 23. Owner decisions required

Do not invent answers: - MVP duration and segment. - Real TTS provider
and voice. - Image provider vs user-supplied image workflow. - BGM/SFX
source (user-supplied/licensed vs generation provider). - FFmpeg
installation permission/method. - Local-only vs cloud/hybrid and
budget. - Output profile (720p/1080p, FPS, codec, loudness). - Required
review gates before expensive generation/final render. - Asset
retention/cache policy and output directory. - Premiere version/import
format.

**End of master specification.**
