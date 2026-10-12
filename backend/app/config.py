from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    database_path: Path
    default_timezone: str = "Asia/Taipei"
    inference_provider: str = "stub"
    local_model_name: str = "qwen2.5:1.5b"
    local_model_base_url: str = "http://127.0.0.1:11434"
    max_import_bytes: int = 8 * 1024 * 1024


def get_settings(database_path: str | Path | None = None) -> Settings:
    return Settings(
        database_path=Path(database_path or os.getenv("DATABASE_PATH", "./data/recall-sidecar.db")),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Asia/Taipei"),
        inference_provider=os.getenv("INFERENCE_PROVIDER", "stub"),
        local_model_name=os.getenv("LOCAL_MODEL_NAME", "qwen2.5:1.5b"),
        local_model_base_url=os.getenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434"),
    )

