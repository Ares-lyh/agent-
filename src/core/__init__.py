from src.core.exceptions import (
    MusicAgentException,
    WorkflowGateViolationError,
    MaterialIncompleteError,
    AudioCorruptedError,
    RateLimitExceededError,
    ModelTimeoutError,
    PromptInjectionDetectedError,
    ProjectNotFoundError,
    CheckpointCorruptError,
)
from src.core.state_machine import ProjectState, StateMachine

from src.core.security import detect_prompt_injection, sanitize_and_wrap_prompt

__all__ = [
    "MusicAgentException",
    "WorkflowGateViolationError",
    "MaterialIncompleteError",
    "AudioCorruptedError",
    "RateLimitExceededError",
    "ModelTimeoutError",
    "PromptInjectionDetectedError",
    "ProjectNotFoundError",
    "CheckpointCorruptError",
    "ProjectState",
    "StateMachine",
    "ProjectCheckpoint",
    "CheckpointManager",
    "detect_prompt_injection",
    "sanitize_and_wrap_prompt",
]


def __getattr__(name):
    if name in ("ProjectCheckpoint", "CheckpointManager"):
        from src.core.checkpoint import ProjectCheckpoint, CheckpointManager
        return {"ProjectCheckpoint": ProjectCheckpoint, "CheckpointManager": CheckpointManager}[name]
    raise AttributeError(name)
