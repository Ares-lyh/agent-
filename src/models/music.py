"""Music generation and composition contracts."""
from typing import List, Optional, Union
from pydantic import Field
from src.models.common import Contract
from src.models.composition import SectionArrangement
from src.models.lyrics import LyricSection
from src.models.plan import StagePlan

class CompositionPlan(Contract):
    bpm: int = Field(gt=30, lt=300)
    key: str
    arrangement_notes: str
    section_arrangements: List[SectionArrangement] = Field(min_length=1)


class ProviderSectionArrangement(Contract):
    """Provider-facing adapter: some models serialize prose as one-item lists."""
    section: Optional[str] = None
    section_name: Optional[str] = None
    emotion: Optional[Union[str, List[str]]] = None
    energy: Optional[Union[str, List[str]]] = None
    instruments: List[str] = Field(default_factory=list)
    instrumentation: Optional[Union[str, List[str]]] = None
    dynamic_level: Optional[Union[str, List[str]]] = None


class CompositionPlanProviderDraft(Contract):
    """Strict Pydantic adapter before normalizing known provider serialization quirks."""
    bpm: int = Field(gt=30, lt=300)
    key: str
    arrangement_notes: Union[str, List[str]]
    section_arrangements: List[ProviderSectionArrangement] = Field(min_length=1)


class CompositionPlanAttempt(Contract):
    attempt: int
    model: str
    raw_response: str
    validation_error: Optional[str] = None

class MusicGenerationRequest(Contract):
    prompt: str
    tags: str
    title: str
    duration: int = Field(gt=0)
    make_instrumental: bool = False

class ResponseFormat(Contract):
    type: str = "json_object"

class ChatMessage(Contract):
    role: str
    content: str

class ChatRequest(Contract):
    model: str
    messages: List[ChatMessage]
    response_format: Optional[ResponseFormat] = Field(default_factory=ResponseFormat)
    temperature: Optional[float] = .7

class ChatChoice(Contract):
    message: ChatMessage

class ChatResponse(Contract):
    choices: List[ChatChoice] = Field(min_length=1)

class LyricsDraft(Contract):
    title: str = Field(min_length=1)
    structure_summary: str
    sections: List[LyricSection] = Field(min_length=1)

class TaskPlanDraft(Contract):
    summary: str
    stages: List[StagePlan] = Field(min_length=1)
    estimated_duration_seconds: int = Field(gt=0)
    key_constraints: List[str]
