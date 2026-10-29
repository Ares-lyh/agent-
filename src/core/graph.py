"""Deterministic three-agent graph backed by an atomic business transaction log.

Each node reloads checkpoint.json. Graph replay cannot grant approvals, and every
external operation is reserved before it starts. Review commands are the only
writers of human decisions.
"""
import hashlib
import json
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from src.core.graph_checkpoint import SQLiteGraphSaver
from src.models.workflow import MusicGraphState, PendingOperation, ProjectCheckpoint
from src.models.common import ExecutionEvent
from src.models.brief import Brief
from src.models.plan import TaskPlan
from src.models.lyrics import Lyrics
from src.models.composition import Composition
from src.models.approval import ApprovalLedger, ApprovalRecord
from src.core.checkpoint import CheckpointManager
from src.core.state_machine import ProjectState, StateMachine
from src.core.exceptions import WorkflowGateViolationError
from src.agents.lyrics_agent import LyricsAgent
from src.agents.audio_agent import AudioAgent
from src.services.llm_service import LLMService
from src.services.packager import ReleasePackager
from src.utils.persistence import atomic_write, next_version, project_lock
from src.utils.hash_utils import calculate_sha256
from src.utils.audio_utils import inspect_and_validate_wav
from src.tools.acoustic_qc_tool import inspect_acoustic_quality
from src.config import settings


def brief_digest(brief):
    excluded = {"cover_placeholder_path"}
    if brief.vocals is None:
        excluded.add("vocals")  # Preserve the identity of pre-vocals checkpoints.
    return hashlib.sha256(json.dumps(brief.model_dump(exclude=excluded),
                         sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class MusicGraphEngine:
    def __init__(self, checkpoint_manager=None, llm_service=None, lyrics_agent=None,
                 audio_agent=None, packager=None):
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(settings.BASE_STORAGE_DIR)
        self.llm_service = llm_service or LLMService()
        self.lyrics_agent = lyrics_agent or LyricsAgent(self.llm_service)
        self.audio_agent = audio_agent or AudioAgent()
        self.packager = packager or ReleasePackager(settings.PACKAGES_DIR)
        builder = StateGraph(MusicGraphState)
        builder.add_node("plan_node", self._node_plan)
        builder.add_node("lyrics_node", self._node_lyrics)
        builder.add_node("audio_node", self._node_audio)
        builder.add_node("package_node", self._node_package)
        builder.add_conditional_edges(START, self._route,
            {"plan": "plan_node", "lyrics": "lyrics_node", "audio": "audio_node",
             "package": "package_node", "wait": END})
        builder.add_edge("plan_node", "lyrics_node")
        builder.add_edge("lyrics_node", "lyrics_review")
        builder.add_edge("audio_node", "audio_review")
        builder.add_edge("package_node", END)
        # checkpoint.json is the authoritative file checkpointer. Each invocation
        # reconstructs its Pydantic state and routes from the persisted operation.
        builder.add_node("lyrics_review", self._review_gate)
        builder.add_node("audio_review", self._review_gate)
        self.graph_saver = SQLiteGraphSaver(Path(self.checkpoint_manager.base_storage_dir)/"workflow.sqlite3")
        for gate in ("lyrics_review", "audio_review"):
            builder.add_conditional_edges(gate, self._route,
                {"plan":"plan_node","lyrics":"lyrics_node","audio":"audio_node",
                 "package":"package_node","wait":END})
        self.graph = builder.compile(checkpointer=self.graph_saver)

    def _review_gate(self, state):
        cp = self.load(state.project_id)
        if cp.pending or cp.state not in (ProjectState.LYRICS_READY,ProjectState.AUDIO_READY):
            return {"project_id": cp.project_id}
        interrupt({"project_id": cp.project_id, "stage": cp.state.value,
                   "message": "等待显式人工审核命令；LLM 输出不能批准"})
        return {"project_id": cp.project_id}

    def directory(self, project_id):
        return Path(self.checkpoint_manager.get_project_dir(project_id))

    def load(self, project_id):
        cp = self.checkpoint_manager.load_checkpoint(project_id)
        if cp.approvals is None:
            path = self.directory(project_id) / "approvals.json"
            cp.approvals = (ApprovalLedger.model_validate_json(path.read_text(encoding="utf-8"))
                            if path.exists() else ApprovalLedger(project_id=project_id))
        return cp

    def save(self, cp):
        self.checkpoint_manager.save_checkpoint(cp)
        # Audit mirror is recoverable from the authoritative checkpoint.
        atomic_write(self.directory(cp.project_id) / "approvals.json", cp.approvals.model_dump_json(indent=2))

    def event(self, cp, stage, action, details, status="SUCCESS"):
        cp.events.append(ExecutionEvent(stage=stage, action=action, details=details, status=status))

    def brief(self, project_id):
        path = self.directory(project_id)/"brief.json"
        cp = self.checkpoint_manager.load_checkpoint(project_id)
        if not path.exists() or cp.brief_mirror_pending:
            if cp.brief_snapshot is None:
                raise ValueError("需求单缺失，且没有可恢复的快照")
            atomic_write(path, cp.brief_snapshot.model_dump_json(indent=2))
            if cp.brief_mirror_pending:
                cp.brief_mirror_pending = False
                self.save(cp)
        return Brief.model_validate_json(path.read_text(encoding="utf-8"))

    def update_metadata(self, project_id, brief, stage, details):
        cp = self.load(project_id)
        cp.brief_snapshot = brief
        cp.brief_hash = brief_digest(brief)
        cp.brief_mirror_pending = True
        cp.detected_anomalies = brief.detect_anomalies()
        cp.package_dir = None
        if cp.state in (ProjectState.PACKAGE_READY,ProjectState.PACKAGE_NEEDS_INFO):
            cp.state = ProjectState.PACKAGE_NEEDS_INFO
        self.event(cp,stage,"Human Metadata Update",details)
        self.save(cp)
        atomic_write(self.directory(project_id)/"brief.json",brief.model_dump_json(indent=2))
        cp.brief_mirror_pending = False
        self.save(cp)
        return cp

    def _route(self, state):
        cp = self.load(state.project_id)
        if cp.pending:
            if cp.pending.stage == "lyrics" and not (self.directory(cp.project_id) / "plan.json").exists():
                return "plan"
            return cp.pending.stage
        if cp.state == ProjectState.NEW:
            return "plan"
        if cp.state == ProjectState.LYRICS_APPROVED:
            return "audio"
        if cp.state == ProjectState.AUDIO_APPROVED:
            return "package"
        return "wait"

    def _node_plan(self, state):
        cp = self.load(state.project_id)
        path = self.directory(cp.project_id) / "plan.json"
        if not path.exists():
            plan = self.llm_service.generate_task_plan(self.brief(cp.project_id))
            if plan.project_id != cp.project_id:
                raise ValueError("计划项目 ID 不匹配")
            atomic_write(path, plan.model_dump_json(indent=2))
        else:
            plan = TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))
            if plan.project_id != cp.project_id:
                raise ValueError("恢复计划项目 ID 不匹配")
        if "plan_generation" not in cp.completed_stages:
            self.event(cp, "PLAN", "Task Planning", "已生成并校验依赖计划")
            cp.completed_stages.append("plan_generation")
            self.save(cp)
        return {"project_id": cp.project_id}

    def _reserve(self, cp, stage, feedback=None, target_dir=None):
        folder = self.directory(cp.project_id) / stage
        requested = cp.audio_version if stage == "audio" else cp.lyrics_version
        if stage == "package":
            folder = Path(target_dir or self.packager.output_root) / cp.project_id
            requested = "v1"
        cp.pending = PendingOperation(stage=stage, version=next_version(folder, requested),
                                      feedback=feedback, target_dir=target_dir)
        self.event(cp, stage.upper(), "Started", f"开始 {cp.pending.version}")
        self.save(cp)

    def _assert_plan_dependency(self, cp, assigned_agent):
        plan = TaskPlan.model_validate_json((self.directory(cp.project_id)/"plan.json").read_text(encoding="utf-8"))
        completed = set()
        human_gate = 0
        for stage in plan.stages:
            if stage.assigned_agent == assigned_agent:
                if not set(stage.dependencies).issubset(completed):
                    raise WorkflowGateViolationError("任务计划的前置依赖尚未完成")
                return
            if stage.assigned_agent == "MasterAgent":
                done = "plan_generation" in cp.completed_stages
            elif stage.assigned_agent == "LyricsAgent":
                done = "lyrics_generation" in cp.completed_stages
            elif stage.assigned_agent == "HumanReviewer":
                human_gate += 1
                done = ("lyrics_approved" if human_gate == 1 else "audio_approved") in cp.completed_stages
            elif stage.assigned_agent == "AudioAgent":
                done = "audio_generation" in cp.completed_stages
            else:
                raise ValueError("计划指定了不受支持的 Agent")
            if done:
                completed.add(stage.stage_id)
        raise ValueError("计划中缺少指定 Agent")

    def _node_lyrics(self, state):
        cp = self.load(state.project_id)
        if cp.pending is None and cp.state != ProjectState.NEW:
            return {"project_id": cp.project_id}
        if cp.pending is None:
            self._reserve(cp, "lyrics")
        self._assert_plan_dependency(cp,"LyricsAgent")
        operation = cp.pending
        path = self.directory(cp.project_id) / "lyrics" / f"{operation.version}.json"
        if path.exists():
            if operation.result_sha256 and calculate_sha256(str(path)) != operation.result_sha256:
                raise WorkflowGateViolationError("待提交歌词与事务凭证哈希不一致")
            lyrics = Lyrics.model_validate_json(path.read_text(encoding="utf-8"))
        else:
            lyrics = self.lyrics_agent.generate(str(self.directory(cp.project_id)),
                     self.brief(cp.project_id), operation.version, operation.feedback, reserved=True)
        if lyrics.version != operation.version or lyrics.project_id != cp.project_id:
            raise ValueError("歌词事务版本或项目 ID 不匹配")
        if operation.result_sha256 is None:
            operation.result_sha256 = calculate_sha256(str(path))
            self.save(cp)
        cp.lyrics_version = lyrics.version
        cp.state = ProjectState.LYRICS_READY
        cp.pending = None
        cp.last_error = None
        cp.completed_stages = list(dict.fromkeys(cp.completed_stages + ["lyrics_generation"]))
        self.event(cp, "LYRICS", "Generated", f"歌词 {lyrics.version} 已就绪，等待人工审核")
        self.save(cp)
        return {"project_id": cp.project_id}

    def assert_lyrics_approval(self, cp):
        path = self.directory(cp.project_id) / "lyrics" / f"{cp.lyrics_version}.json"
        if not path.exists() or not cp.approvals.is_stage_approved(
                "lyrics", cp.lyrics_version, calculate_sha256(str(path))):
            raise WorkflowGateViolationError("当前歌词版本没有有效的人工批准，或审核后内容已改变")

    def _node_audio(self, state):
        cp = self.load(state.project_id)
        StateMachine.assert_lyrics_approved(cp.state, cp.project_id)
        if cp.pending is None and cp.state != ProjectState.LYRICS_APPROVED:
            return {"project_id": cp.project_id}
        self.assert_lyrics_approval(cp)
        self._assert_plan_dependency(cp,"AudioAgent")
        if cp.pending is None:
            self._reserve(cp, "audio")
        operation = cp.pending
        directory = self.directory(cp.project_id)
        lyrics = Lyrics.model_validate_json((directory / "lyrics" / f"{cp.lyrics_version}.json").read_text(encoding="utf-8"))
        comp_path = directory / "audio" / f"{operation.version}_comp.json"
        if comp_path.exists():
            if operation.result_related_sha256 and calculate_sha256(str(comp_path)) != operation.result_related_sha256:
                raise WorkflowGateViolationError("待提交编曲与事务凭证哈希不一致")
            comp = Composition.model_validate_json(comp_path.read_text(encoding="utf-8"))
            if (comp.operation_id != operation.operation_id or comp.lyrics_sha256 !=
                    calculate_sha256(str(directory / "lyrics" / f"{cp.lyrics_version}.json"))):
                raise ValueError("恢复产物的事务或歌词哈希不匹配")
            inspection = inspect_and_validate_wav(comp.audio_metadata.file_path)
            if not inspection.is_valid or inspection.sha256 != comp.audio_metadata.sha256:
                raise ValueError("恢复音频文件损坏")
        else:
            def remember_task(task_id):
                operation.task_id = task_id
                self.save(cp)
            comp = self.audio_agent.generate(
                str(directory), self.brief(cp.project_id), lyrics, operation.version,
                feedback=operation.feedback, approval_ledger=cp.approvals, reserved=True,
                operation_id=operation.operation_id, task_id=operation.task_id,
                on_task=remember_task)
        if operation.result_sha256 is None:
            operation.result_sha256 = comp.audio_metadata.sha256
            operation.result_related_sha256 = calculate_sha256(str(comp_path))
            self.save(cp)
        cp.audio_version = comp.composition_version
        cp.composition_version = comp.composition_version
        cp.state = ProjectState.AUDIO_READY
        cp.pending = None
        cp.last_error = None
        cp.completed_stages = list(dict.fromkeys(cp.completed_stages + ["audio_generation"]))
        self.event(cp, "AUDIO", "Generated", f"音频 {comp.composition_version} 已完成，等待人工试听")
        self.save(cp)
        return {"project_id": cp.project_id}

    def _node_package(self, state):
        cp = self.load(state.project_id)
        self._export(cp)
        return {"project_id": cp.project_id}

    def prepare_start(self, brief_data):
        """Commit the initial transaction before a web worker or CLI invokes models."""
        brief = brief_data if isinstance(brief_data, Brief) else Brief.model_validate(brief_data)
        directory = self.directory(brief.project_id)
        with project_lock(directory):
            if self.checkpoint_manager.project_exists(brief.project_id):
                cp = self.load(brief.project_id)
                expected = cp.brief_hash or brief_digest(self.brief(brief.project_id))
                if expected != brief_digest(brief):
                    raise ValueError("同一项目 ID 的需求单已改变；请使用新项目 ID")
            else:
                cp = ProjectCheckpoint(project_id=brief.project_id, state=ProjectState.NEW,
                    brief_hash=brief_digest(brief), brief_snapshot=brief, approvals=ApprovalLedger(project_id=brief.project_id),
                    detected_anomalies=brief.detect_anomalies(), completed_stages=["brief_parsing"])
                self.event(cp, "INIT", "Brief Ingestion", "已保存需求单")
                self.save(cp)
                atomic_write(directory / "brief.json", brief.model_dump_json(indent=2))
                self._reserve(cp, "lyrics")
            return self.load(brief.project_id)

    def start(self, brief_data, raw_content=None):
        brief = brief_data if isinstance(brief_data, Brief) else Brief.model_validate(brief_data)
        self.prepare_start(brief)
        directory = self.directory(brief.project_id)
        with project_lock(directory):
            cp = self.load(brief.project_id)
            if cp.state == ProjectState.NEW or cp.pending:
                self._invoke(cp)
            cp = self.load(brief.project_id)
            return (cp, TaskPlan.model_validate_json((directory / "plan.json").read_text(encoding="utf-8")),
                    Lyrics.model_validate_json((directory / "lyrics" / f"{cp.lyrics_version}.json").read_text(encoding="utf-8")))

    def _invoke(self, cp):
        try:
            config = {"configurable":{"thread_id":cp.project_id}}
            snapshot = self.graph.get_state(config)
            interrupted = any(task.interrupts for task in snapshot.tasks)
            graph_input = (Command(resume=True) if interrupted else None if snapshot.next
                           else MusicGraphState(project_id=cp.project_id))
            self.graph.invoke(graph_input,config=config)
        except Exception as exc:
            current = self.load(cp.project_id)
            current.last_error = str(exc)
            self.event(current, "ERROR", "Failed", str(exc), "FAILED")
            self.save(current)
            raise

    def approve_stage(self, project_id, stage, approved=True, reviewer="Human Reviewer", feedback=None):
        with project_lock(self.directory(project_id)):
            cp = self.load(project_id)
            if stage not in ("lyrics", "audio"):
                raise ValueError("未知的审核阶段")
            if cp.pending:
                raise WorkflowGateViolationError("有未完成的任务，请先 resume 恢复")
            expected = ProjectState.LYRICS_READY if stage == "lyrics" else ProjectState.AUDIO_READY
            # Rejection may explicitly invalidate a later approval; never an earlier stage.
            allowed_reject = ({ProjectState.LYRICS_READY, ProjectState.LYRICS_APPROVED,
                ProjectState.AUDIO_READY, ProjectState.AUDIO_APPROVED, ProjectState.PACKAGE_READY,
                ProjectState.PACKAGE_NEEDS_INFO} if stage == "lyrics" else
                {ProjectState.AUDIO_READY, ProjectState.AUDIO_APPROVED, ProjectState.PACKAGE_READY,
                 ProjectState.PACKAGE_NEEDS_INFO})
            reapproval = approved and stage == "lyrics" and cp.state in allowed_reject
            if (approved and cp.state != expected and not reapproval) or (not approved and cp.state not in allowed_reject):
                raise WorkflowGateViolationError(f"当前状态 {cp.state.value} 不能审核 {stage}")
            directory = self.directory(project_id)
            version = cp.lyrics_version if stage == "lyrics" else cp.audio_version
            artifact = directory / stage / (f"{version}.json" if stage == "lyrics" else f"{version}_audio.wav")
            related = None
            if stage == "audio":
                self.assert_lyrics_approval(cp)
                comp_path = directory / "audio" / f"{cp.composition_version}_comp.json"
                comp = Composition.model_validate_json(comp_path.read_text(encoding="utf-8"))
                inspection = inspect_acoustic_quality(str(artifact))
                if approved and (not inspection.is_valid or inspection.sha256 != comp.audio_metadata.sha256):
                    raise WorkflowGateViolationError("音频无效或生成后被修改")
                if approved and (comp.project_id != project_id or comp.lyrics_version != cp.lyrics_version
                        or comp.lyrics_sha256 != calculate_sha256(str(directory/"lyrics"/f"{cp.lyrics_version}.json"))):
                    raise WorkflowGateViolationError("编曲尚未绑定当前歌词，请驳回音频生成新版本")
                related = calculate_sha256(str(comp_path))
            if stage == "lyrics":
                lyric = Lyrics.model_validate_json(artifact.read_text(encoding="utf-8"))
                if lyric.project_id != project_id or lyric.version != version:
                    raise WorkflowGateViolationError("歌词项目或版本不匹配")
            record = ApprovalRecord(project_id=project_id, stage=stage, approved=approved,
                     target_version=version, artifact_sha256=calculate_sha256(str(artifact)),
                     related_sha256=related, reviewer=reviewer, feedback=feedback).seal()
            cp.approvals.records.append(record)
            cp.package_dir = None
            if approved:
                target = ProjectState.LYRICS_APPROVED if stage == "lyrics" else ProjectState.AUDIO_APPROVED
                StateMachine.assert_transition(cp.state,target,project_id)
                if stage == "lyrics" and cp.state != ProjectState.LYRICS_READY:
                    cp.completed_stages = [s for s in cp.completed_stages if s not in
                                           ("audio_generation","audio_approved","package_exported")]
                cp.state = ProjectState.LYRICS_APPROVED if stage == "lyrics" else ProjectState.AUDIO_APPROVED
                cp.completed_stages = list(dict.fromkeys(cp.completed_stages + [stage + "_approved"]))
                self.event(cp, stage.upper(), "Human Approved", f"{version} by {reviewer}")
                self.save(cp)
            else:
                target = ProjectState.LYRICS_READY if stage == "lyrics" else ProjectState.LYRICS_APPROVED
                StateMachine.assert_transition(cp.state,target,project_id)
                cp.state = target
                cp.completed_stages = [s for s in cp.completed_stages if s not in
                    (["lyrics_approved", "audio_generation", "audio_approved", "package_exported"] if stage == "lyrics"
                     else ["audio_approved", "package_exported"])]
                # Decision and pending regeneration commit together, before any model call.
                self._reserve(cp, stage, feedback or "请重新创作并改善上一版本")
                self._invoke(cp)
            return self.load(project_id)

    def resume(self, project_id):
        with project_lock(self.directory(project_id)):
            self.brief(project_id)  # Heal a metadata mirror interrupted after checkpoint commit.
            cp = self.load(project_id)
            if cp.pending or cp.state in (ProjectState.NEW, ProjectState.LYRICS_APPROVED, ProjectState.AUDIO_APPROVED):
                self._invoke(cp)
            cp = self.load(project_id)
            messages = {
                ProjectState.LYRICS_READY: "等待人工审核歌词",
                ProjectState.LYRICS_APPROVED: "歌词已批准，等待音频生成",
                ProjectState.AUDIO_READY: "已完成作曲与音频生成，等待人工试听审核",
                ProjectState.PACKAGE_READY: "物料包构建完成",
                ProjectState.PACKAGE_NEEDS_INFO: "物料包构建完成，需补齐或修复物料",
            }
            return cp, messages.get(cp.state, cp.state.value)

    def export_package(self, project_id, target_dir=None):
        with project_lock(self.directory(project_id)):
            try:
                return self._export(self.load(project_id), target_dir)
            except Exception as exc:
                current = self.load(project_id)
                current.last_error = str(exc)
                self.event(current,"ERROR","Export Failed",str(exc),"FAILED")
                self.save(current)
                raise

    def _export(self, cp, target_dir=None):
        StateMachine.assert_audio_approved(cp.state, cp.project_id)
        if cp.pending and cp.pending.stage != "package":
            raise WorkflowGateViolationError("创作任务未完成，不能打包")
        if not cp.pending:
            self._reserve(cp, "package", target_dir=target_dir)
        directory = self.directory(cp.project_id)
        def optional(model, path):
            try:
                return model.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        lyrics = optional(Lyrics, directory / "lyrics" / f"{cp.lyrics_version}.json")
        comp = optional(Composition, directory / "audio" / f"{cp.composition_version}_comp.json")
        manifest, package_dir = self.packager.build_package(
            str(directory), self.brief(cp.project_id), lyrics, comp, cp.approvals,
            (directory / "brief.json").read_text(encoding="utf-8"),
            target_dir=cp.pending.target_dir, package_version=cp.pending.version,
            lyrics_version=cp.lyrics_version, audio_version=cp.audio_version,
            initial_issues=["需求单内容与已登记哈希不一致"] if cp.brief_hash and cp.brief_hash != brief_digest(self.brief(cp.project_id)) else [])
        cp.state = ProjectState.PACKAGE_READY if manifest.package_status == "ready" else ProjectState.PACKAGE_NEEDS_INFO
        cp.package_dir = package_dir
        cp.package_version = manifest.package_version
        cp.pending = None
        cp.last_error = None
        cp.completed_stages = list(dict.fromkeys(cp.completed_stages + ["package_exported"]))
        self.event(cp, "DELIVERY", "Package Built", f"{manifest.package_version}: {manifest.package_status}")
        self.save(cp)
        return manifest, package_dir
