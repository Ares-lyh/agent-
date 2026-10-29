"""Global Configuration Management."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load .env if present
load_dotenv()


class Settings:
    # DeepSeek / OpenAI / Codex API Configuration
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY") or os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("CODEX_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL") or os.getenv("CODEX_MODEL") or os.getenv("OPENAI_MODEL") or "deepseek-chat"
    
    # Offline demo is explicit; production errors never fall back.
    USE_MOCK_LLM: bool = os.getenv("USE_MOCK_LLM", "false").lower() in ("true", "1", "yes")

    # Mock Music Model Resilience Simulation
    MOCK_AUDIO_DELAY_SECONDS: float = float(os.getenv("MOCK_AUDIO_DELAY_SECONDS", "0.05"))
    MOCK_AUDIO_SAMPLE_DURATION: float = float(os.getenv("MOCK_AUDIO_SAMPLE_DURATION", "0"))
    MOCK_AUDIO_SIMULATE_429: bool = os.getenv("MOCK_AUDIO_SIMULATE_429", "false").lower() in ("true", "1", "yes")
    MOCK_AUDIO_SIMULATE_EMPTY: bool = os.getenv("MOCK_AUDIO_SIMULATE_EMPTY", "false").lower() in ("true", "1", "yes")
    MOCK_AUDIO_SIMULATE_TIMEOUT: bool = os.getenv("MOCK_AUDIO_SIMULATE_TIMEOUT", "false").lower() in ("true", "1", "yes")

    # Native ACEMusic or documented generic gateway; mock is explicit demo only.
    MUSIC_PROVIDER: str = os.getenv("MUSIC_PROVIDER", "unconfigured").lower()
    REAL_MUSIC_API_KEY: str = os.getenv("REAL_MUSIC_API_KEY", "")
    REAL_MUSIC_BASE_URL: str = os.getenv("REAL_MUSIC_BASE_URL", "")
    ACEMUSIC_MODEL: str = os.getenv("ACEMUSIC_MODEL", "acemusic/acestep-v1.5-turbo")
    SUNO_API_KEY: str = os.getenv("SUNO_API_KEY", "")
    SUNO_BASE_URL: str = os.getenv("SUNO_BASE_URL", "")
    MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
    MINIMAX_GROUP_ID: str = os.getenv("MINIMAX_GROUP_ID", "")

    MUSIC_API_PROTOCOL: str = os.getenv("MUSIC_API_PROTOCOL", "gateway")
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    LYRICS_MAX_REVISIONS: int = int(os.getenv("LYRICS_MAX_REVISIONS", "2"))

    # Storage Paths
    BASE_STORAGE_DIR: str = os.getenv("BASE_STORAGE_DIR", "storage/projects")
    PACKAGES_DIR: str = os.getenv("PACKAGES_DIR", "release-package")


settings = Settings()
