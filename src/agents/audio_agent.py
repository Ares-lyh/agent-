"""Approved-lyrics-only composition, generation, conversion and acoustic QC."""
from pathlib import Path
from src.agents.base import BaseAgent, retry_with_backoff
from src.models.composition import Composition, AudioMetadata
from src.models.common import GenerationParameters
from src.models.approval import ApprovalLedger
from src.tools.music_api_tool import RealMusicEngineClient
from src.tools.acoustic_qc_tool import inspect_acoustic_quality
from src.utils.persistence import atomic_write, next_version, publish, project_lock
from src.utils.hash_utils import calculate_sha256
from src.core.exceptions import AudioCorruptedError, WorkflowGateViolationError
from src.config import settings
from src.models.vocals import AudioGenerationIntent
from src.services.vocal_direction import resolve_vocals

class AudioAgent(BaseAgent):
    def __init__(self, music_model=None, llm_service=None):
        super().__init__("AudioAgent")
        self.client = music_model if music_model is not None else RealMusicEngineClient()
        if isinstance(getattr(self.client,"client",None),RealMusicEngineClient):
            self.client = self.client.client
        self.llm_service = llm_service

    def _infer_musical_parameters(self, genre, mood):
        if "摇滚" in genre or "rock" in genre.lower():
            return 138, "G Major"
        if "电子" in genre:
            return 128, "D Minor"
        return 85, "C Major"

    def generate(self, project_dir, brief, lyrics, version="v1", is_lyrics_approved=False,
                 feedback=None, approval_ledger=None, reserved=False, operation_id=None,
                 task_id=None, on_task=None):
        lyrics_path = Path(project_dir) / "lyrics" / f"{lyrics.version}.json"
        if (not approval_ledger or approval_ledger.project_id != brief.project_id
                or lyrics.project_id != brief.project_id or not lyrics_path.exists()
                or not approval_ledger.is_stage_approved("lyrics", lyrics.version,
                                                        calculate_sha256(str(lyrics_path)))):
            raise WorkflowGateViolationError("歌词尚未通过人工审核批准，或批准未绑定当前内容")
        folder = Path(project_dir) / "audio"
        folder.mkdir(parents=True, exist_ok=True)
        if not reserved:
            with project_lock(folder):
                version = next_version(folder, version)
                return self.generate(project_dir, brief, lyrics, version, feedback=feedback,
                    approval_ledger=approval_ledger, reserved=True, operation_id=operation_id,
                    task_id=task_id, on_task=on_task)
        audio_path = folder / f"{version}_audio.wav"
        comp_path = folder / f"{version}_comp.json"
        temporary = folder / f".{version}_audio.part.wav"
        if comp_path.exists():
            raise FileExistsError("禁止覆盖历史编曲")
        if audio_path.exists():
            # A crash after publishing audio but before composition cannot overwrite it.
            temporary = audio_path
        bpm, key = self._infer_musical_parameters(brief.genre, brief.mood)
        if feedback and ("减半" in feedback or "halve" in feedback.lower()):
            bpm = max(31, bpm // 2)
        if audio_path.exists():
            draft = folder / f".{version}_draft.json"
            if not draft.exists():
                raise AudioCorruptedError("发现没有编曲凭证的音轨，禁止覆盖；请检查后重新分配版本")
            comp = Composition.model_validate_json(draft.read_text(encoding="utf-8"))
            if comp.audio_metadata.sha256 != calculate_sha256(str(audio_path)):
                raise AudioCorruptedError("恢复音轨与编曲凭证哈希不一致")
        elif hasattr(self.client, "generate"):
            draft = folder / f".{version}_draft.json"
            if temporary.exists() and draft.exists():
                comp = Composition.model_validate_json(draft.read_text(encoding="utf-8"))
                if comp.audio_metadata.sha256 != calculate_sha256(str(temporary)):
                    raise AudioCorruptedError("临时音轨与恢复凭证不匹配")
            else:
                comp = self._legacy(brief.project_id,brief,lyrics,str(temporary),version,feedback)
                atomic_write(draft, comp.model_dump_json(indent=2))
        else:
            self.client.validate_configuration()
            vocals = resolve_vocals(brief, feedback)
            plan = None
            plan_path = folder / f".{version}_plan.json"
            if self.llm_service is not None:
                from src.models.music import CompositionPlan
                if plan_path.exists():
                    plan = CompositionPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
                else:
                    def remember_attempt(attempt):
                        atomic_write(folder / f".{version}_plan-attempt-{attempt.attempt}.json", attempt.model_dump_json(indent=2))
                    plan = self.llm_service.generate_composition_plan(brief, lyrics, feedback, on_attempt=remember_attempt)
                    atomic_write(plan_path, plan.model_dump_json(indent=2))
                bpm, key = plan.bpm, plan.key
                if [section.section_name for section in plan.section_arrangements] != [section.section_name for section in lyrics.sections]:
                    raise ValueError("编曲方案必须按顺序覆盖全部歌词段落")
            if not audio_path.exists():
                generation_prompt = (plan.arrangement_notes if plan else f"{brief.genre}; {brief.mood}")
                generation_prompt = "\n".join(filter(None, (
                    "REQUIRED VOCAL DIRECTION: " + vocals.instruction() if vocals.instruction() else "",
                    "用户参考：" + "；".join(brief.references),
                    "创作约束：" + "；".join(brief.constraints), generation_prompt)))
                generation_prompt += "\n修改意见：" + (feedback or "首次生成")
                if plan:
                    generation_prompt += "\n编曲方案：" + plan.model_dump_json()
                if vocals.instruction():
                    generation_prompt += "\n全曲必须保持的人声目标：" + vocals.instruction()
                if self.client.provider != "acemusic":
                    generation_prompt = lyrics.to_markdown() + "\n" + generation_prompt
                intent = AudioGenerationIntent(project_id=brief.project_id, version=version,
                    provider=self.client.provider, prompt=generation_prompt, vocal_requirements=vocals)
                intent_path = folder / f".{version}_generation-intent.json"
                if intent_path.exists():
                    previous = AudioGenerationIntent.model_validate_json(intent_path.read_text(encoding="utf-8"))
                    if previous != intent:
                        raise WorkflowGateViolationError("当前音频任务的人声目标或提示词发生变化；请为新目标分配新版本")
                else:
                    atomic_write(intent_path, intent.model_dump_json(indent=2))
                result = self.client.submit_and_wait(
                    prompt=generation_prompt,
                    genre=brief.genre, mood=brief.mood, bpm=bpm, key=key,
                    duration_seconds=brief.duration_seconds, output_wav_path=str(temporary),
                    task_id=task_id, on_task=on_task, idempotency_key=operation_id,
                    lyrics="\n\n".join("[" + section.section_type + "]\n" + "\n".join(section.lines)
                                           for section in lyrics.sections),
                    vocal_language=brief.lyrics_language)
            validated_audio = inspect_acoustic_quality(str(temporary))
            if not validated_audio.is_valid:
                raise AudioCorruptedError(validated_audio.error_message)
            comp = Composition(project_id=brief.project_id, composition_version=version,
                bpm=bpm, key=key, genre=brief.genre, mood=brief.mood,
                arrangement_notes=plan.arrangement_notes if plan else f"{brief.genre} / {brief.mood}",
                vocal_requirements=vocals,
                section_arrangements=plan.section_arrangements if plan else [],
                music_model_params=GenerationParameters(provider=self.client.provider,
                    model=self.client.model,
                    task_id=(result.task_id if not audio_path.exists() else task_id),
                    target_duration_s=brief.duration_seconds, feedback=feedback,
                    is_mock=self.client.is_mock),
                audio_metadata=AudioMetadata(duration_seconds=validated_audio.duration_seconds,
                    file_size_bytes=validated_audio.file_size_bytes, file_path=str(audio_path),
                    sha256=validated_audio.sha256),
                handoff_notes="等待声学检查与人工试听")
        qc = inspect_acoustic_quality(str(temporary))
        if not qc.is_valid:
            raise AudioCorruptedError(f"音频未通过声学检查: {qc.error_message}")
        tolerance = max(2.0, brief.duration_seconds * .05)
        if abs(qc.duration_seconds - brief.duration_seconds) > tolerance:
            raise AudioCorruptedError(f"音频时长 {qc.duration_seconds}s 与需求 {brief.duration_seconds}s 不符")
        comp.composition_version = version
        comp.lyrics_version = lyrics.version
        comp.lyrics_sha256 = calculate_sha256(str(lyrics_path))
        comp.operation_id = operation_id
        comp.audio_metadata = AudioMetadata(format="wav", sample_rate=qc.sample_rate, channels=qc.channels,
            bit_depth=qc.bit_depth, duration_seconds=qc.duration_seconds,
            file_size_bytes=qc.file_size_bytes, file_path=str(audio_path), sha256=qc.sha256)
        comp.music_model_params.feedback = feedback
        comp.handoff_notes = f"版本 {version}; {audio_path}; SHA-256 {qc.sha256}; 等待人工审核"
        atomic_write(folder / f".{version}_draft.json", comp.model_dump_json(indent=2))
        if temporary != audio_path:
            publish(temporary, audio_path)
        comp_temp = folder / f".{version}_comp.part.json"
        atomic_write(comp_temp, comp.model_dump_json(indent=2))
        publish(comp_temp, comp_path)
        return comp

    @retry_with_backoff(max_retries=3)
    def _legacy(self, project_id, brief, lyrics, output_path, version, feedback):
        return self.client.generate(project_id=project_id,brief=brief,lyrics=lyrics,
                                    output_audio_path=output_path,version=version,feedback=feedback)
