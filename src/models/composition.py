"""Composition and Audio Metadata Schema."""
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from src.models.common import Contract, GenerationParameters
from src.models.vocals import VocalRequirements


class SectionArrangement(Contract):
    section: Optional[str] = None
    section_name: Optional[str] = None
    emotion: Optional[str] = None
    energy: Optional[str] = None
    instruments: List[str] = Field(default_factory=list)
    instrumentation: Optional[str] = None
    dynamic_level: Optional[str] = None


class AudioMetadata(Contract):
    format: str = "wav"
    sample_rate: int = 44100
    channels: int = 2
    bit_depth: int = 16
    duration_seconds: float = Field(gt=0)
    file_size_bytes: int = Field(gt=0)
    file_path: str
    sha256: str


class Composition(Contract):
    project_id: str
    composition_version: str = "v1"
    bpm: int = Field(gt=30, lt=300, description="BPM 节拍速度")
    key: str = Field(description="调性 Key, 例如 C Major, A Minor")
    genre: str
    mood: str
    arrangement_notes: str = Field(description="段落与编曲说明")
    vocal_requirements: Optional[VocalRequirements] = None
    lyrics_version: str = "v1"
    lyrics_sha256: Optional[str] = None
    operation_id: Optional[str] = None
    section_arrangements: List[SectionArrangement] = Field(default_factory=list, description="各段落编曲细节")
    music_model_params: GenerationParameters = Field(default_factory=GenerationParameters, description="音乐生成模型参数")
    audio_metadata: AudioMetadata
    handoff_notes: str = Field(description="给下游的 handoff 说明与产物清单")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
