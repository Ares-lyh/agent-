"""Shared validated contracts."""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

def utc_now():
    return datetime.now(timezone.utc).isoformat()

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    def get(self, key, default=None):
        return getattr(self, key, default)
    def __getitem__(self, key):
        return getattr(self, key)

class GenerationParameters(Contract):
    model: Optional[str] = None
    engine: Optional[str] = None
    model_engine: Optional[str] = None
    provider: str = "unknown"
    temperature: float = 0.7
    version: str = "v1"
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bit_depth: Optional[int] = None
    allow_sampling: bool = False
    target_duration_s: Optional[float] = None
    task_id: Optional[str] = None
    feedback: Optional[str] = None
    is_mock: bool = False

class AudioInspectionResult(Contract):
    is_valid: bool
    format: str = "wav"
    sample_rate: int = 0
    channels: int = 0
    bit_depth: int = 0
    duration_seconds: float = 0
    file_size_bytes: int = 0
    sha256: str = ""
    clipping_ratio: float = 0
    silence_ratio: float = 0
    error_message: Optional[str] = None

class ExecutionEvent(Contract):
    timestamp: str = Field(default_factory=utc_now)
    stage: str
    action: str
    details: str
    status: str = "SUCCESS"


class QualityLineStat(Contract):
    line_number: int
    text: str
    char_count: int
    last_char: str
    rhyme_vowel: Optional[str] = None


class RhymeAnalysisResult(Contract):
    line_stats: list[QualityLineStat]
    detected_rhymes: dict[str, list[int]] = Field(default_factory=dict)
    rhyme_scheme: str = "Free"
    average_syllables: float = 0
    meter_regularity: float = 0
    feedback_notes: list[str] = Field(default_factory=list)
