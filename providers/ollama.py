import json
from typing import Any

import httpx

from providers.base import BaseProvider, ProviderTimeoutError, ProviderUnavailableError


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1",
        timeout: float = 120.0,
        max_retries: int = 3,
        temperature: float = 0.7,
    ):
        super().__init__("OllamaProvider")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.temperature = temperature
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> dict[str, Any]:
        prompt = self._render_prompt(inputs)
        response = self._call_ollama(prompt)
        return self._parse_response(response, inputs)

    def _render_prompt(self, inputs: dict[str, Any], stage: str | None = None) -> str:
        from pathlib import Path

        import jinja2

        prompts_dir = Path(__file__).parent.parent / "prompts"
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(prompts_dir)))
        target_stage = stage or inputs.get("stage", "story")
        template_name = f"{target_stage}.j2"
        try:
            template = env.get_template(template_name)
        except jinja2.TemplateNotFound as e:
            raise FileNotFoundError(
                f"Prompt template '{template_name}' not found for stage "
                f"'{target_stage}' in {prompts_dir}"
            ) from e
        return template.render(**inputs)

    def _call_ollama(self, prompt: str) -> dict:
        url = "/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            }
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
                f"Ollama request timed out after {self.timeout}s. "
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
            "approval_status": "pending"
        }

    def _extract_json_from_text(self, text: str) -> dict:
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _get_timestamp(self) -> str:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat()
