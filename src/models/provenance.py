"""Artifact origin is independent of the currently selected runtime provider."""
from typing import Literal, Optional
from src.models.common import Contract


class ArtifactProvenance(Contract):
    mode: Literal["real", "mock", "unknown", "missing"]
    provider: str = "unknown"
    model: Optional[str] = None
    version: Optional[str] = None
    message: str
