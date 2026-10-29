"""Tests for StateMachine transitions and gate enforcement."""
import pytest
from src.core.state_machine import ProjectState, StateMachine
from src.core.exceptions import WorkflowGateViolationError


def test_legal_forward_transitions():
    """Verify standard legal forward path."""
    assert StateMachine.validate_transition(ProjectState.NEW, ProjectState.LYRICS_READY)
    assert StateMachine.validate_transition(ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED)
    assert StateMachine.validate_transition(ProjectState.LYRICS_APPROVED, ProjectState.AUDIO_READY)
    assert StateMachine.validate_transition(ProjectState.AUDIO_READY, ProjectState.AUDIO_APPROVED)
    assert StateMachine.validate_transition(ProjectState.AUDIO_APPROVED, ProjectState.PACKAGE_READY)
    assert StateMachine.validate_transition(ProjectState.AUDIO_APPROVED, ProjectState.PACKAGE_NEEDS_INFO)


def test_illegal_jump_transitions_blocked():
    """Verify illegal jumps are blocked with WorkflowGateViolationError."""
    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_transition(ProjectState.NEW, ProjectState.AUDIO_READY, "song_001")

    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_transition(ProjectState.NEW, ProjectState.PACKAGE_READY, "song_001")

    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_transition(ProjectState.LYRICS_READY, ProjectState.PACKAGE_READY, "song_001")


def test_scenario_1_unapproved_lyrics_cannot_call_audio():
    """Scenario 1: 歌词未审核就调用作曲，严格拦截."""
    # When state is lyrics_ready (not approved yet)
    with pytest.raises(WorkflowGateViolationError) as exc_info:
        StateMachine.assert_lyrics_approved(ProjectState.LYRICS_READY, "song_001")
    assert "歌词尚未通过人工审核批准" in str(exc_info.value) or "未通过" in str(exc_info.value) or "尚未" in str(exc_info.value)

    # When state is new
    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_lyrics_approved(ProjectState.NEW, "song_001")


def test_scenario_9_lyrics_rejection_branch():
    """Scenario 9: 歌词审核拒绝后回到修改阶段，绝不允许流向作曲."""
    # lyrics_ready rejected should transition back to lyrics_ready (for modification)
    assert StateMachine.validate_transition(ProjectState.LYRICS_READY, ProjectState.LYRICS_READY)

    # State remains LYRICS_READY, calling audio must be blocked
    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_lyrics_approved(ProjectState.LYRICS_READY, "song_001")


def test_unapproved_audio_cannot_package():
    """Verify packaging requires audio_approved."""
    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_audio_approved(ProjectState.AUDIO_READY, "song_001")
    with pytest.raises(WorkflowGateViolationError):
        StateMachine.assert_audio_approved(ProjectState.LYRICS_APPROVED, "song_001")
