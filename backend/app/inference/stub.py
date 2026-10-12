class DeterministicStubProvider:
    name = "DeterministicStubProvider"
    is_local = True

    def generate_text(self, prompt: str) -> str:
        return ""

    def generate_structured(self, prompt: str, schema):
        return schema()

    def healthcheck(self) -> dict:
        return {"status": "ready", "provider": self.name, "model": "deterministic-rules-v1", "is_local": True}

