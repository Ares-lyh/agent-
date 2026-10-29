"""Master Agent (Orchestrator) coordinating child agents, HITL gates, and packaging."""
import os
import json
from typing import Optional, Dict, Any, Tuple
from src.agents.base import BaseAgent
from src.agents.lyrics_agent import LyricsAgent
from src.agents.audio_agent import AudioAgent
from src.models.brief import Brief, BriefAnomaly
from src.models.plan import TaskPlan
from src.models.lyrics import Lyrics
from src.models.composition import Composition
from src.models.approval import ApprovalRecord, ApprovalLedger
from src.models.manifest import Manifest
from src.core.state_machine import ProjectState, StateMachine
from src.core.checkpoint import ProjectCheckpoint, CheckpointManager
from src.core.exceptions import (
    WorkflowGateViolationError,
    ProjectNotFoundError,
    MaterialIncompleteError,
)
from src.services.llm_service import LLMService
from src.services.mock_music_model import MockMusicModel
from src.services.packager import ReleasePackager
from src.services.reporter import RunReport, ExecutionEvent
from src.core.graph import MusicGraphEngine
from src.config import settings


class MasterAgent(BaseAgent):
    """Central orchestrator managing pipeline lifecycle, HITL review, and release packaging."""

    def __init__(
        self,
        checkpoint_manager: Optional[CheckpointManager] = None,
        llm_service: Optional[LLMService] = None,
        music_model: Optional[MockMusicModel] = None,
        packager: Optional[ReleasePackager] = None,
    ):
        super().__init__(agent_name="MasterAgent")
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(settings.BASE_STORAGE_DIR)
        self.llm_service = llm_service or LLMService()
        self.lyrics_agent = LyricsAgent(llm_service=self.llm_service)
        self.audio_agent = AudioAgent(music_model=music_model, llm_service=self.llm_service)
        self.packager = packager or ReleasePackager(settings.PACKAGES_DIR)
        self.graph_engine = MusicGraphEngine(
            checkpoint_manager=self.checkpoint_manager,
            llm_service=self.llm_service,
            lyrics_agent=self.lyrics_agent,
            audio_agent=self.audio_agent,
            packager=self.packager,
        )

    def start_from_brief_file(self, brief_path: str) -> Tuple[ProjectCheckpoint, TaskPlan, Lyrics]:
        """Entry point: Initialize project from a brief file, validate, and run to lyrics_ready."""
        if not os.path.exists(brief_path):
            raise FileNotFoundError(f"需求单文件不存在: {brief_path}")

        with open(brief_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
            brief_model = Brief.model_validate_json(raw_content)

        return self.start(brief_model, raw_content=raw_content)

    def start(self, brief_data: Brief, raw_content: Optional[str] = None) -> Tuple[ProjectCheckpoint, TaskPlan, Lyrics]:
        """Start or resume pipeline using LangGraph Multi-Agent StateGraph."""
        result = self.graph_engine.start(brief_data, raw_content=raw_content)
        self.generate_report(result[0].project_id)
        return result

    def approve_stage(
        self,
        project_id: str,
        stage: str,
        approved: bool = True,
        reviewer: str = "Human Reviewer",
        feedback: Optional[str] = None,
    ) -> ProjectCheckpoint:
        """Process human review decisions for lyrics or audio via LangGraph."""
        checkpoint = self.graph_engine.approve_stage(
            project_id=project_id,
            stage=stage,
            approved=approved,
            reviewer=reviewer,
            feedback=feedback,
        )
        self.generate_report(project_id)
        return checkpoint

    def resume(self, project_id: str) -> Tuple[ProjectCheckpoint, str]:
        """Resume execution from saved checkpoint via LangGraph."""
        checkpoint, message = self.graph_engine.resume(project_id)
        self.generate_report(project_id, pkg_dir=checkpoint.package_dir or "")
        return checkpoint, message

    def export_package(self, project_id, target_dir=None):
        manifest, pkg_dir = self.graph_engine.export_package(project_id, target_dir)
        self.generate_report(project_id, manifest, pkg_dir)
        return manifest, pkg_dir

    def generate_report(self, project_id: str, manifest: Optional[Manifest] = None, pkg_dir: str = "") -> RunReport:
        """Compile and write comprehensive run report."""
        checkpoint = self.checkpoint_manager.load_checkpoint(project_id)
        project_dir = self.checkpoint_manager.get_project_dir(project_id)
        brief = self._load_brief(project_id)
        try:
            lyrics = self._load_latest_lyrics(project_id, checkpoint.lyrics_version)
        except (OSError, ValueError):
            lyrics = None
        ledger = checkpoint.approvals or self._load_or_create_ledger(project_id)

        approvals_summary = {stage: record for stage in ("lyrics", "audio")
                             for record in [ledger.get_latest_record(stage)] if record}

        artifact_paths = {
            "checkpoint": self.checkpoint_manager.get_checkpoint_path(project_id),
            "brief": os.path.join(project_dir, "brief.json"),
            "plan": os.path.join(project_dir, "plan.json"),
            "lyrics": os.path.join(project_dir, "lyrics", f"{checkpoint.lyrics_version}.json"),
            "audio": os.path.join(project_dir, "audio", f"{checkpoint.audio_version}_audio.wav"),
            "approvals": os.path.join(project_dir, "approvals.json"),
        }
        if pkg_dir:
            artifact_paths["release_package"] = pkg_dir

        timeline = checkpoint.events

        report = RunReport(
            project_id=project_id,
            song_title=lyrics.title if lyrics else project_id,
            genre=brief.genre,
            mood=brief.mood,
            current_state=checkpoint.state.value,
            packaging_status=manifest.package_status if manifest else ("ready" if checkpoint.state == ProjectState.PACKAGE_READY else "needs_info" if checkpoint.state == ProjectState.PACKAGE_NEEDS_INFO else None),
            anomalies_detected=checkpoint.detected_anomalies,
            approvals_summary=approvals_summary,
            execution_timeline=timeline,
            artifact_paths=artifact_paths,
        )

        from src.utils.persistence import atomic_write
        atomic_write(os.path.join(project_dir, "run_report.json"), report.model_dump_json(indent=2))
        atomic_write(os.path.join(project_dir, "run_report.md"), report.to_markdown())

        return report

    # Internal Loaders
    def _load_brief(self, project_id: str) -> Brief:
        return self.graph_engine.brief(project_id)

    def _load_plan(self, project_id: str) -> TaskPlan:
        path = os.path.join(self.checkpoint_manager.get_project_dir(project_id), "plan.json")
        with open(path, "r", encoding="utf-8") as f:
            return TaskPlan.model_validate_json(f.read())

    def _load_latest_lyrics(self, project_id: str, version: str) -> Lyrics:
        path = os.path.join(self.checkpoint_manager.get_project_dir(project_id), "lyrics", f"{version}.json")
        with open(path, "r", encoding="utf-8") as f:
            return Lyrics.model_validate_json(f.read())

    def _load_latest_composition(self, project_id: str, version: str) -> Composition:
        path = os.path.join(self.checkpoint_manager.get_project_dir(project_id), "audio", f"{version}_comp.json")
        with open(path, "r", encoding="utf-8") as f:
            return Composition.model_validate_json(f.read())

    def _load_or_create_ledger(self, project_id: str) -> ApprovalLedger:
        checkpoint = self.graph_engine.load(project_id)
        if checkpoint.approvals is not None:
            return checkpoint.approvals
        path = os.path.join(self.checkpoint_manager.get_project_dir(project_id), "approvals.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return ApprovalLedger.model_validate_json(f.read())
        return ApprovalLedger(project_id=project_id)

