from __future__ import annotations

import json
import urllib.request


class MacLocalProvider:
    """Optional Ollama-compatible provider. Never falls back to cloud."""
    is_local = True
    supports_generation = True

    def __init__(self, base_url: str, model: str, timeout: float = 30):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.name = f"MacLocalProvider ({model})"

    def generate_text(self, prompt: str, *, options: dict | None = None, response_format=None) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False,
                   "options": {"num_ctx": 4096, "temperature": 0, "num_predict": 256}}
        if options:
            payload["options"].update(options)
        if response_format is not None:
            payload["format"] = response_format
        body = json.dumps(payload).encode()
        request = urllib.request.Request(self.base_url + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())["response"]

    def generate_structured(self, prompt: str, schema):
        # Ollama accepts a Pydantic JSON schema in `format`; validation remains
        # server-side so malformed or hallucinated output can safely fall back.
        response_format = schema.model_json_schema() if hasattr(schema, "model_json_schema") else "json"
        return schema.model_validate_json(self.generate_text(prompt, response_format=response_format))

    def healthcheck(self) -> dict:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=2) as response:
                if response.status != 200:
                    return {"status": "unavailable", "provider": self.name, "model": self.model, "is_local": True}
                payload = json.loads(response.read())
                models = {item.get("name") for item in payload.get("models", [])}
                installed = self.model in models
                return {"status": "ready" if installed else "model_missing", "provider": self.name,
                        "model": self.model, "is_local": True, "installed_models": sorted(models)}
        except Exception:
            return {"status": "unavailable", "provider": self.name, "model": self.model, "is_local": True}
