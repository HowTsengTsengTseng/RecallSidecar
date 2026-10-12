from __future__ import annotations

import json
import urllib.request


class MacLocalProvider:
    """Optional Ollama-compatible provider. Never falls back to cloud."""
    is_local = True

    def __init__(self, base_url: str, model: str, timeout: float = 30):
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.name = f"MacLocalProvider ({model})"

    def generate_text(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False, "options": {"num_predict": 256}}).encode()
        request = urllib.request.Request(self.base_url + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())["response"]

    def generate_structured(self, prompt: str, schema):
        return schema.model_validate_json(self.generate_text(prompt))

    def healthcheck(self) -> dict:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags", timeout=2) as response:
                return {"status": "ready" if response.status == 200 else "unavailable", "provider": self.name, "model": self.model, "is_local": True}
        except Exception:
            return {"status": "unavailable", "provider": self.name, "model": self.model, "is_local": True}

