class HailoInferenceProvider:
    """Stage II integration boundary; intentionally unavailable on the Stage I Mac host."""
    name = "HailoInferenceProvider"
    is_local = True

    def generate_text(self, prompt: str) -> str:
        raise RuntimeError("HailoRT integration is available only after Linux + UGen300 hardware validation")

    def generate_structured(self, prompt: str, schema):
        raise RuntimeError("HailoRT integration is not configured")

    def healthcheck(self) -> dict:
        return {"status": "not_configured", "provider": self.name, "model": None, "is_local": True, "benchmark": "TBD - measure on hardware"}

