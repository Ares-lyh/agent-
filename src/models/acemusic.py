"""ACEMusic's documented OpenRouter-compatible music API contracts."""
from typing import List, Literal, Optional
from pydantic import ConfigDict, Field
from src.models.common import Contract
from src.models.music import ChatMessage


class AudioConfig(Contract):
    duration: float = Field(gt=0)
    format: Literal["wav"] = "wav"
    bpm: int = Field(gt=30, lt=300)
    key_scale: str
    vocal_language: str
    instrumental: bool = False


class MusicRequest(Contract):
    model: str
    messages: List[ChatMessage] = Field(min_length=1)
    lyrics: str = Field(min_length=1)
    audio_config: AudioConfig
    stream: Literal[False] = False
    sample_mode: Literal[False] = False
    use_format: Literal[False] = False
    use_cot_caption: Literal[False] = False
    use_cot_language: Literal[False] = False
    thinking: Literal[False] = False
    batch_size: Literal[1] = 1


class ProviderResponse(Contract):
    # Providers may add envelope metadata; business fields stay strongly typed.
    model_config = ConfigDict(extra="ignore")


class AudioURL(ProviderResponse):
    url: str = Field(min_length=1)


class AudioOutput(ProviderResponse):
    type: Literal["audio_url"]
    audio_url: AudioURL


class AssistantMessage(ProviderResponse):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    audio: List[AudioOutput] = Field(min_length=1)


class Choice(ProviderResponse):
    message: AssistantMessage
    finish_reason: Literal["stop"] = "stop"


class MusicResponse(ProviderResponse):
    id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    choices: List[Choice] = Field(min_length=1)


class Pricing(ProviderResponse):
    prompt: str = "0"
    completion: str = "0"
    request: str = "0"


class ModelInfo(ProviderResponse):
    id: str
    output_modalities: List[str] = Field(default_factory=list)
    pricing: Optional[Pricing] = None


class ModelsResponse(ProviderResponse):
    data: List[ModelInfo] = Field(min_length=1)
