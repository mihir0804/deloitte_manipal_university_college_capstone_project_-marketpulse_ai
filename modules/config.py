"""Central configuration for MarketPulse AI & Campaign Studio.

All credentials come from environment variables (optionally via a local .env
file).  Nothing sensitive is ever hard-coded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DATA_DIR = PROJECT_ROOT / "data"
EXPORT_DIR = PROJECT_ROOT / "exports"
DB_PATH = Path(os.environ.get("MARKOTPULSE_DB", str(DATA_DIR / "marketpulse.db")))
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLE_CSV = ASSETS_DIR / "sample_feedback.csv"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {".csv", ".txt", ".md", ".markdown", ".pdf", ".docx"}


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).  Existing env wins."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


@dataclass
class AIConfig:
    provider: str = field(default_factory=lambda: os.environ.get("MARPULSE_AI_PROVIDER", "none").lower())
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.environ.get("GOOGLE_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))
    timeout_seconds: int = field(default_factory=lambda: int(os.environ.get("MARPULSE_AI_TIMEOUT", "60")))
    max_retries: int = field(default_factory=lambda: int(os.environ.get("MARPULSE_AI_RETRIES", "2")))

    def available(self) -> bool:
        if self.provider == "openai":
            return bool(self.openai_api_key)
        if self.provider == "gemini":
            return bool(self.gemini_api_key or self.google_api_key)
        return False

    def display_name(self) -> str:
        if self.provider == "openai" and self.openai_api_key:
            return f"OpenAI ({self.openai_model})"
        if self.provider == "gemini" and (self.gemini_api_key or self.google_api_key):
            return f"Google Gemini ({self.gemini_model})"
        return "Local Analysis Mode (deterministic)"


def get_ai_config() -> AIConfig:
    return AIConfig()


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR, ASSETS_DIR):
        d.mkdir(parents=True, exist_ok=True)
