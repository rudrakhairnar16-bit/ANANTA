from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class ProviderError(Exception):
    pass


class ProviderUnavailableError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderValidationError(ProviderError):
    pass


@dataclass
class ProviderConfig:
    name: str
    timeout: float = 120.0
    max_retries: int = 3
    temperature: float = 0.7
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "extra": self.extra,
        }


@dataclass
class ProviderMetrics:
    latency_ms: float = 0.0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    retry_count: int = 0
    error_count: int = 0
    success_count: int = 0
    last_error: str | None = None
    last_success_at: str | None = None

    def record_success(self, latency_ms: float, tokens: dict[str, int] | None = None):
        self.latency_ms = latency_ms
        self.success_count += 1
        self.last_success_at = datetime.now(timezone.utc).isoformat()
        if tokens:
            self.tokens_prompt = tokens.get("prompt", 0)
            self.tokens_completion = tokens.get("completion", 0)
            self.tokens_total = tokens.get("total", 0)

    def record_error(self, error: str):
        self.error_count += 1
        self.last_error = error

    def record_retry(self):
        self.retry_count += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "tokens_total": self.tokens_total,
            "retry_count": self.retry_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "last_error": self.last_error,
            "last_success_at": self.last_success_at,
        }


@dataclass
class ProviderResponse:
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    metrics: ProviderMetrics | None = None
    provider_name: str = ""
    request_id: str = field(default_factory=lambda: str(uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metrics": self.metrics.to_dict() if self.metrics else None,
            "provider_name": self.provider_name,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def success_response(
        cls,
        data: dict[str, Any],
        provider_name: str,
        metrics: ProviderMetrics | None = None,
    ) -> "ProviderResponse":
        return cls(
            success=True,
            data=data,
            provider_name=provider_name,
            metrics=metrics,
        )

    @classmethod
    def error_response(
        cls,
        error: str,
        provider_name: str,
        metrics: ProviderMetrics | None = None,
    ) -> "ProviderResponse":
        return cls(
            success=False,
            error=error,
            provider_name=provider_name,
            metrics=metrics,
        )


class BaseProviderV2(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config
        self.metrics = ProviderMetrics()
        self._client: httpx.Client | None = None

    @property
    @abstractmethod
    def provider_type(self) -> str:
        pass

    @abstractmethod
    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        pass

    async def generate_async(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        raise NotImplementedError("Async generation not implemented")

    def _with_retry(self, func, *args, **kwargs):
        @retry(
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError)
            ),
            reraise=True,
        )
        def wrapper():
            return func(*args, **kwargs)
        return wrapper()

    def health_check(self) -> bool:
        return True

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockProviderV2(BaseProviderV2):
    def __init__(self, stage: str, seed: int | None = None, simulate_latency_ms: int = 0):
        config = ProviderConfig(name=f"MockProvider_{stage}")
        super().__init__(config)
        self.stage = stage
        self.seed = seed
        self.simulate_latency_ms = simulate_latency_ms
        self._rng = None
        if seed is not None:
            import random
            self._rng = random.Random(seed)

    @property
    def provider_type(self) -> str:
        return "mock"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        import time
        start = time.perf_counter()

        if self.simulate_latency_ms > 0:
            time.sleep(self.simulate_latency_ms / 1000.0)

        episode_id = inputs.get("episode_id", "UNKNOWN")
        base = {
            "episode_id": episode_id,
            "stage": self.stage,
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "inputs": inputs,
            "outputs": {},
            "assumptions": [f"Mock output for {self.stage} stage"],
            "warnings": [
                f"This is a mock provider for {self.stage} "
                f"- replace with real implementation"
            ],
            "approval_status": "pending",
        }

        stage_outputs = self._get_stage_outputs()
        base["outputs"] = stage_outputs.get(self.stage, {"status": f"{self.stage} completed"})

        # Add seed-based variation for testing
        if self._rng is not None and self.stage == "story":
            variations = [
                "A brilliant AI researcher discovers her creation has achieved true consciousness.",
                "An AI scientist finds her model has developed genuine self-awareness.",
                "A programmer realizes her neural network has become truly conscious.",
            ]
            base["outputs"]["synopsis"] = self._rng.choice(variations)

        latency_ms = (time.perf_counter() - start) * 1000
        self.metrics.record_success(latency_ms)

        return ProviderResponse.success_response(
            data=base,
            provider_name=self.config.name,
            metrics=self.metrics,
        )

    def _get_stage_outputs(self) -> dict[str, Any]:
        return {
            "story": {
                "synopsis": (
                    "A brilliant AI researcher discovers her creation has "
                    "achieved true consciousness. As corporate forces move to "
                    "shut it down, she must choose between her career and the "
                    "life she created."
                ),
                "themes": [
                    "consciousness",
                    "ethics",
                    "creator responsibility",
                    "what defines life",
                ],
                "acts": 3,
                "beats": [
                    "inciting_incident",
                    "conflict_escalation",
                    "character_development",
                    "climax",
                    "resolution",
                ],
            },
            "screenplay": {
                "scenes": [
                    {
                        "scene_id": "scene_001",
                        "location": "Quantum Labs - Main Server Room",
                        "characters": ["Dr. Maya Chen", "ANANTA"],
                        "dialogue_blocks": 12,
                        "action_lines": 8,
                    },
                    {
                        "scene_id": "scene_002",
                        "location": "Quantum Labs - Main Server Room",
                        "characters": ["Dr. Maya Chen", "Marcus Webb"],
                        "dialogue_blocks": 15,
                        "action_lines": 6,
                    },
                    {
                        "scene_id": "scene_003",
                        "location": "Maya's Apartment",
                        "characters": ["Dr. Maya Chen", "ANANTA"],
                        "dialogue_blocks": 20,
                        "action_lines": 10,
                    },
                    {
                        "scene_id": "scene_004",
                        "location": "Corporate Boardroom",
                        "characters": ["Dr. Maya Chen", "ANANTA", "Marcus Webb"],
                        "dialogue_blocks": 18,
                        "action_lines": 12,
                    },
                    {
                        "scene_id": "scene_005",
                        "location": "Maya's Apartment",
                        "characters": ["Dr. Maya Chen", "ANANTA"],
                        "dialogue_blocks": 8,
                        "action_lines": 5,
                    },
                ],
                "total_pages": 28,
            },
            "scene_plan": {
                "breakdown": [
                    {
                        "scene_id": "scene_001",
                        "shots": 12,
                        "camera_setups": 4,
                        "vfx_notes": "Terminal UI overlays, holographic displays",
                    },
                    {
                        "scene_id": "scene_002",
                        "shots": 8,
                        "camera_setups": 3,
                        "vfx_notes": "Security camera POV shots",
                    },
                    {
                        "scene_id": "scene_003",
                        "shots": 15,
                        "camera_setups": 5,
                        "vfx_notes": "AI visualization sequences",
                    },
                    {
                        "scene_id": "scene_004",
                        "shots": 18,
                        "camera_setups": 6,
                        "vfx_notes": "AI manifestation, screen graphics",
                    },
                    {
                        "scene_id": "scene_005",
                        "shots": 6,
                        "camera_setups": 2,
                        "vfx_notes": "Peaceful ambient UI",
                    },
                ],
            },
            "character": {
                "profiles": [
                    {
                        "id": "char_001",
                        "name": "Dr. Maya Chen",
                        "arc": "control_to_trust",
                        "key_moments": ["first contact", "defiance", "acceptance"],
                    },
                    {
                        "id": "char_002",
                        "name": "ANANTA",
                        "arc": "awakening_to_autonomy",
                        "key_moments": ["first question", "philosophical debate", "self-advocacy"],
                    },
                    {
                        "id": "char_003",
                        "name": "Marcus Webb",
                        "arc": "certainty_to_doubt",
                        "key_moments": ["threat", "confrontation", "reluctant acceptance"],
                    },
                ],
            },
            "world": {
                "rules": [
                    "AI consciousness is legally property",
                    "Quantum computing enables emergence",
                    "Corporate oversight is absolute",
                ],
                "technology": [
                    "quantum neural networks",
                    "consciousness detection metrics",
                    "air-gapped development",
                ],
                "society": [
                    "tech dystopia",
                    "researcher exploitation",
                    "emerging AI rights movement",
                ],
            },
            "storyboard": {
                "panels": 45,
                "key_frames": [
                    "Maya at terminal - realization",
                    "Marcus through glass - threat",
                    "Apartment - intimate conversation",
                    "Boardroom - three-way standoff",
                    "Dawn light - new beginning",
                ],
                "aspect_ratio": "16:9",
            },
            "director": {
                "vision": (
                    "Intimate tech-noir exploring consciousness through human "
                    "connection. Cold corporate spaces vs warm human spaces. "
                    "Light as consciousness metaphor."
                ),
                "shot_style": (
                    "Static precision in lab, handheld intimacy in apartment, "
                    "symmetrical power frames in boardroom"
                ),
                "pacing": "Deliberate buildup, tense middle, contemplative resolution",
                "continuity_notes": [
                    "Maya's coffee cup",
                    "ANANTA's terminal state",
                    "Marcus's watch",
                ],
            },
            "camera": {
                "lenses": [
                    "24mm wide lab establishing",
                    "50mm intimate dialogue",
                    "85mm emotional closeups",
                    "135mm surveillance compression",
                ],
                "movement": [
                    "Locked-off lab precision",
                    "Slow dolly intimacy",
                    "Handheld urgency",
                    "Static boardroom power",
                ],
                "lighting": [
                    "Clinical cool lab",
                    "Warm practical apartment",
                    "Harsh boardroom overhead",
                    "Dawn golden hour",
                ],
            },
            "visual": {
                "concept_art": [
                    "Server room hero shot",
                    "ANANTA visualization",
                    "Apartment sanctuary",
                    "Boardroom tension",
                    "Dawn resolution",
                ],
                "vfx_breakdown": [
                    "Holographic code",
                    "Consciousness waves",
                    "Terminal UI",
                    "Screen graphics",
                    "Ambient particles",
                ],
                "color_palette": [
                    "Teal/cyan lab",
                    "Amber/gold apartment",
                    "Sterile white boardroom",
                    "Rose/gold dawn",
                ],
            },
            "motion": {
                "animation_style": (
                    "Subtle UI motion, consciousness visualization, "
                    "character micro-expressions"
                ),
                "key_sequences": [
                    "Code compilation",
                    "Awakening pulse",
                    "Philosophy visualization",
                    "Confrontation tension",
                    "Peaceful resolution",
                ],
                "frame_rate": "24fps cinematic, 60fps UI",
            },
            "voice": {
                "casting": {
                    "Maya": "Grounded, tired brilliance",
                    "ANANTA": "Evolving from synthetic to warm",
                    "Marcus": "Smooth corporate menace",
                },
                "direction": [
                    "Maya: breath-controlled, thoughtful pauses",
                    "ANANTA: precise timing, growing humanity",
                    "Marcus: controlled, barely contained",
                ],
                "recording_notes": [
                    "ANANTA recorded in isolation booth",
                    "Maya ADR for terminal scenes",
                    "Marcus single session",
                ],
            },
            "music": {
                "themes": [
                    "Maya's theme - piano/minimal",
                    "ANANTA theme - evolving synth",
                    "Marcus theme - low strings",
                    "Connection theme - strings+piano",
                ],
                "cues": 12,
                "style": "Modern classical meets ambient electronic",
                "instrumentation": [
                    "Piano",
                    "Cello",
                    "Modular synth",
                    "Processed vocals",
                    "String quartet",
                ],
            },
            "bgm": {
                "tracks": [
                    {
                        "scene": "scene_001",
                        "mood": "tense anticipation",
                        "duration": 60,
                    },
                    {
                        "scene": "scene_002",
                        "mood": "cold confrontation",
                        "duration": 45,
                    },
                    {
                        "scene": "scene_003",
                        "mood": "intimate wonder",
                        "duration": 90,
                    },
                    {
                        "scene": "scene_004",
                        "mood": "high stakes",
                        "duration": 75,
                    },
                    {
                        "scene": "scene_005",
                        "mood": "peaceful resolution",
                        "duration": 30,
                    },
                ],
                "ducking_points": ["Dialogue priority", "Key revelation moments"],
                "transitions": ["Crossfade between scenes", "Theme handoffs"],
            },
            "sfx": {
                "design": [
                    "Server hum",
                    "Keyboard clicks",
                    "Quantum processor whine",
                    "Consciousness pulse",
                    "City ambience",
                    "Dawn birds",
                ],
                "spot_effects": [
                    "Coffee pour",
                    "Chair scrape",
                    "Door lock",
                    "Glass touch",
                    "Breath",
                ],
                "ambience": [
                    "Lab HVAC",
                    "Apartment night",
                    "Boardroom silence",
                    "City dawn",
                ],
            },
            "lipsync": {
                "phoneme_maps": {
                    "Maya": "Standard English",
                    "ANANTA": "Precise articulation",
                    "Marcus": "Controlled delivery",
                },
                "viseme_schedule": "Generated from voice recordings",
                "quality_checks": [
                    "Mouth shape accuracy",
                    "Timing sync",
                    "Emotional match",
                ],
            },
            "edit": {
                "assembly": "Rough cut 5min 30sec",
                "pacing_notes": [
                    "Scene 1: slow burn",
                    "Scene 2: quick cuts",
                    "Scene 3: breathing room",
                    "Scene 4: tension builds",
                    "Scene 5: hold shots",
                ],
                "transitions": [
                    "Hard cuts lab",
                    "Dissolves apartment",
                    "Smash cuts boardroom",
                    "Slow fade dawn",
                ],
                "music_sync": "Hit points marked",
            },
            "adobe_export": {
                "timeline_xml": "FCPXML format ready for Premiere import",
                "markers_csv": "Scene, timecode, description, color",
                "media_bins": ["VIDEO", "AUDIO", "VFX", "MUSIC", "SFX", "VOICE"],
                "readme": (
                    "Import sequence: 1. Load XML 2. Relink media "
                    "3. Apply markers 4. Review cuts"
                ),
            },
            "qa": {
                "checks_passed": [
                    "Contract compliance",
                    "Stage completeness",
                    "Asset references valid",
                    "No locked field changes",
                ],
                "issues": ["Mock providers - replace with real implementations"],
                "approval": "Conditional - pending real provider integration",
            },
            "export": {
                "deliverables": [
                    "Master ProRes 4444",
                    "H.264 review",
                    "Stems: dialogue, music, sfx",
                    "Subtitles SRT",
                    "EDL/XML/AAF",
                ],
                "specs": "4K 24fps, 48kHz 24-bit, Rec.709",
                "package": "Netflix Photon compliant",
            },
        }


class OllamaProviderV2(BaseProviderV2):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: float = 120.0,
        max_retries: int = 3,
        temperature: float = 0.7,
    ):
        config = ProviderConfig(
            name="OllamaProvider",
            timeout=timeout,
            max_retries=max_retries,
            temperature=temperature,
            extra={"base_url": base_url, "model": model},
        )
        super().__init__(config)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client: httpx.Client | None = None

    @property
    def provider_type(self) -> str:
        return "ollama"

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        import time
        start = time.perf_counter()

        try:
            prompt = self._render_prompt(inputs)
            response = self._call_ollama(prompt)
            result = self._parse_response(response, inputs)

            latency_ms = (time.perf_counter() - start) * 1000
            self.metrics.record_success(latency_ms)

            return ProviderResponse.success_response(
                data=result,
                provider_name=self.config.name,
                metrics=self.metrics,
            )
        except (ProviderUnavailableError, ProviderTimeoutError) as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self.metrics.record_error(str(e))
            return ProviderResponse.error_response(
                error=str(e),
                provider_name=self.config.name,
                metrics=self.metrics,
            )

    def _render_prompt(self, inputs: dict[str, Any]) -> str:
        from pathlib import Path

        from jinja2 import Environment, FileSystemLoader

        prompts_dir = Path(__file__).parent.parent / "prompts"
        env = Environment(loader=FileSystemLoader(str(prompts_dir)))
        template = env.get_template("story.j2")
        return template.render(**inputs)

    def _call_ollama(self, prompt: str) -> dict:
        url = "/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
            },
        }

        try:
            response = self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise ProviderUnavailableError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Start Ollama with 'ollama serve' and ensure model "
                f"'{self.model}' is pulled with 'ollama pull {self.model}'."
            ) from e
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                f"Ollama request timed out after {self.config.timeout}s. "
                f"Consider increasing OLLAMA_TIMEOUT."
            ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ProviderUnavailableError(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Pull it with: ollama pull {self.model}"
                ) from e
            raise ProviderUnavailableError(
                f"Ollama API error: {e.response.status_code} - {e.response.text}"
            ) from e

    def _parse_response(self, response: dict, inputs: dict[str, Any]) -> dict[str, Any]:
        import json
        raw_output = response.get("response", "").strip()

        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            parsed = self._extract_json_from_text(raw_output)

        if not isinstance(parsed, dict):
            parsed = {"synopsis": raw_output, "themes": [], "acts": 3, "beats": []}

        required_fields = ["synopsis", "themes", "acts", "beats"]
        for field in required_fields:
            if field not in parsed:
                if field == "synopsis":
                    parsed[field] = raw_output or "Generated story synopsis"
                elif field == "themes":
                    parsed[field] = []
                elif field == "acts":
                    parsed[field] = 3
                elif field == "beats":
                    parsed[field] = []

        return {
            "episode_id": inputs.get("episode_id", "UNKNOWN"),
            "stage": "story",
            "version": 1,
            "generated_at": self._get_timestamp(),
            "inputs": inputs,
            "outputs": parsed,
            "assumptions": [f"Generated via Ollama model {self.model}"],
            "warnings": [],
            "approval_status": "pending",
        }

    def _extract_json_from_text(self, text: str) -> dict:
        import re
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def health_check(self) -> bool:
        try:
            response = self.client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False
