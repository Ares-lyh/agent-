"""Domain and System Exceptions."""


class MusicAgentException(Exception):
    """Base exception for Music Agent System."""
    pass


class WorkflowGateViolationError(MusicAgentException):
    """Raised when an illegal state transition or unapproved gate bypass is attempted."""
    pass


class MaterialIncompleteError(MusicAgentException):
    """Raised when mandatory release package materials are missing."""
    pass


class AudioCorruptedError(MusicAgentException):
    """Raised when an audio file is 0 bytes, missing headers, or corrupt."""
    pass


class RateLimitExceededError(MusicAgentException):
    """Raised when music model or LLM returns 429 and retries are exhausted."""
    pass


class ModelTimeoutError(MusicAgentException):
    """Raised when an upstream model call times out."""
    pass


class PromptInjectionDetectedError(MusicAgentException):
    """Raised when an adversarial prompt injection pattern is detected."""
    pass


class ProjectNotFoundError(MusicAgentException):
    """Raised when requested project ID does not exist."""
    pass


class CheckpointCorruptError(MusicAgentException):
    """Raised when checkpoint file cannot be parsed or verified."""
    pass
