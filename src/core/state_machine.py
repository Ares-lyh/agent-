"""Finite State Machine (FSM) enforcing system lifecycle transitions."""
from enum import Enum
from typing import Set, Dict
from src.core.exceptions import WorkflowGateViolationError


class ProjectState(str, Enum):
    NEW = "new"
    LYRICS_READY = "lyrics_ready"
    LYRICS_APPROVED = "lyrics_approved"
    AUDIO_READY = "audio_ready"
    AUDIO_APPROVED = "audio_approved"
    PACKAGE_READY = "package_ready"
    PACKAGE_NEEDS_INFO = "package_needs_info"


# Define legal directed transitions
LEGAL_TRANSITIONS: Dict[ProjectState, Set[ProjectState]] = {
    ProjectState.NEW: {ProjectState.LYRICS_READY},
    # lyrics_ready can be approved -> lyrics_approved, or rejected -> lyrics_ready (for modification)
    ProjectState.LYRICS_READY: {ProjectState.LYRICS_APPROVED, ProjectState.LYRICS_READY, ProjectState.NEW},
    # lyrics_approved can advance to audio_ready
    ProjectState.LYRICS_APPROVED: {ProjectState.AUDIO_READY, ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED},
    # audio_ready can be approved -> audio_approved, or rejected -> audio_ready / lyrics_approved (for re-generation)
    ProjectState.AUDIO_READY: {ProjectState.AUDIO_APPROVED, ProjectState.AUDIO_READY, ProjectState.LYRICS_APPROVED, ProjectState.LYRICS_READY},
    # audio_approved can advance to package_ready or package_needs_info (if materials incomplete)
    ProjectState.AUDIO_APPROVED: {ProjectState.PACKAGE_READY, ProjectState.PACKAGE_NEEDS_INFO, ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED},
    # terminal / delivery states (support idempotent re-export & recovery)
    ProjectState.PACKAGE_READY: {ProjectState.PACKAGE_READY, ProjectState.PACKAGE_NEEDS_INFO, ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED},
    ProjectState.PACKAGE_NEEDS_INFO: {ProjectState.PACKAGE_READY, ProjectState.PACKAGE_NEEDS_INFO, ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED},  # if missing materials are later fixed
}


class StateMachine:
    """State machine controller with hard guardrails."""

    @staticmethod
    def validate_transition(from_state: ProjectState, to_state: ProjectState) -> bool:
        """Check if transition from from_state to to_state is permissible."""
        valid_targets = LEGAL_TRANSITIONS.get(from_state, set())
        return to_state in valid_targets

    @staticmethod
    def assert_transition(from_state: ProjectState, to_state: ProjectState, project_id: str = ""):
        """Assert transition is valid, raise WorkflowGateViolationError otherwise."""
        if not StateMachine.validate_transition(from_state, to_state):
            raise WorkflowGateViolationError(
                f"[工作流门禁阻断] 项目 '{project_id}' 状态非法流转: "
                f"不能从 '{from_state.value}' 直接跳入 '{to_state.value}'！"
                f"合法后继状态集合为: {[s.value for s in LEGAL_TRANSITIONS.get(from_state, set())]}"
            )

    @staticmethod
    def assert_lyrics_approved(current_state: ProjectState, project_id: str = ""):
        """Guardrail: Ensure lyrics are approved before audio generation."""
        allowed_states = {
            ProjectState.LYRICS_APPROVED,
            ProjectState.AUDIO_READY,
            ProjectState.AUDIO_APPROVED,
            ProjectState.PACKAGE_READY,
            ProjectState.PACKAGE_NEEDS_INFO,
        }
        if current_state not in allowed_states:
            raise WorkflowGateViolationError(
                f"[安全门禁阻断] 项目 '{project_id}' 歌词尚未审核批准 (当前状态: {current_state.value})，"
                f"绝对禁止调用作曲/音频生成子 Agent！"
            )

    @staticmethod
    def assert_audio_approved(current_state: ProjectState, project_id: str = ""):
        """Guardrail: Ensure audio is approved before packaging."""
        allowed_states = {
            ProjectState.AUDIO_APPROVED,
            ProjectState.PACKAGE_READY,
            ProjectState.PACKAGE_NEEDS_INFO,
        }
        if current_state not in allowed_states:
            raise WorkflowGateViolationError(
                f"[安全门禁阻断] 项目 '{project_id}' 音频尚未审核批准 (当前状态: {current_state.value})，"
                f"绝对禁止生成最终发行物料包！"
            )
