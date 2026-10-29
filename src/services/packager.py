"""Immutable per-project packages with bound approvals and verified downloads."""
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4
from PIL import Image
from src.models.manifest import Manifest, FileChecksum, AudioFileChecksum
from src.models.lyrics import Lyrics
from src.models.brief import Brief
from src.models.composition import Composition
from src.models.approval import ApprovalLedger
from src.core.exceptions import WorkflowGateViolationError
from src.utils.persistence import atomic_write, next_version
from src.utils.hash_utils import calculate_sha256, calculate_content_sha256
from src.tools.acoustic_qc_tool import inspect_acoustic_quality
from src.config import settings
from src.services.provenance import artifact_provenance

class ReleasePackager:
    def __init__(self, output_root=None):
        self.output_root = output_root or settings.PACKAGES_DIR

    def build_package(self, project_dir, brief, lyrics, composition, approval_ledger,
                      brief_raw_content, target_dir=None, package_version=None,
                      lyrics_version=None, audio_version=None, initial_issues=None):
        root = Path(target_dir or self.output_root).resolve() / brief.project_id
        root.mkdir(parents=True, exist_ok=True)
        version = package_version or next_version(root)
        final = root / version
        # Recover a completed directory rename before checkpoint commit.
        if final.exists():
            manifest = Manifest.model_validate_json((final/"manifest.json").read_text(encoding="utf-8"))
            self.verify_package(str(final), brief.project_id)
            return manifest, str(final)
        staging = root / ("." + version + "." + uuid4().hex + ".tmp")
        staging.mkdir()
        missing, issues = [], list(initial_issues or [])
        directory = Path(project_dir)
        ledger = approval_ledger or ApprovalLedger(project_id=brief.project_id)
        lv = lyrics_version or (lyrics.version if lyrics else "v1")
        av = audio_version or (composition.composition_version if composition else "v1")

        def checksum(name):
            path = staging / name
            return FileChecksum(file_name=name, relative_path=name,
                sha256=calculate_sha256(str(path)) if path.exists() else "",
                size_bytes=path.stat().st_size if path.exists() else 0, exists=path.exists())

        if lyrics is not None:
            atomic_write(staging/"lyrics.md", lyrics.to_markdown())
            source = directory/"lyrics"/f"{lv}.json"
            sha = calculate_sha256(str(source)) if source.exists() else ""
            if source.exists():
                shutil.copyfile(source,staging/"lyrics.json")
            if lyrics.project_id != brief.project_id or lyrics.version != lv:
                issues.append("歌词项目或版本不匹配")
            if not ledger.is_stage_approved("lyrics",lv,sha):
                issues.append("歌词审核版本、内容哈希或审核记录不匹配")
        else:
            missing.append("缺失或损坏歌词 lyrics.md")

        if ledger.project_id != brief.project_id:
            issues.append("审核账本项目 ID 不匹配")
        audio = AudioFileChecksum(duration_seconds=0,sample_rate=0,channels=0,bit_depth=0,
                                  sha256="",size_bytes=0,exists=False)
        if composition is not None:
            comp = composition.model_copy(deep=True)
            original_audio = Path(comp.audio_metadata.file_path)
            if not original_audio.is_absolute():
                original_audio = Path.cwd()/original_audio
            if comp.project_id != brief.project_id or comp.composition_version != av:
                issues.append("编曲项目或版本不匹配")
            source_lyrics = directory/"lyrics"/f"{lv}.json"
            lyric_hash = calculate_sha256(str(source_lyrics)) if source_lyrics.exists() else ""
            if comp.lyrics_version != lv or comp.lyrics_sha256 != lyric_hash:
                issues.append("编曲未绑定当前审核歌词")
            comp_source = directory/"audio"/f"{av}_comp.json"
            comp_hash = calculate_sha256(str(comp_source)) if comp_source.exists() else ""
            if comp_source.exists():
                shutil.copyfile(comp_source,staging/"composition-source.json")
            if original_audio.is_file() and original_audio.stat().st_size:
                shutil.copyfile(original_audio, staging/"audio.wav")
                inspection = inspect_acoustic_quality(str(staging/"audio.wav"))
                audio = AudioFileChecksum(duration_seconds=inspection.duration_seconds,
                    sample_rate=inspection.sample_rate,channels=inspection.channels,bit_depth=inspection.bit_depth,
                    sha256=inspection.sha256,size_bytes=inspection.file_size_bytes,exists=True)
                if not inspection.is_valid:
                    issues.append("音频文件损坏或声学检查失败: "+str(inspection.error_message))
                if inspection.sha256 != comp.audio_metadata.sha256:
                    issues.append("音频文件哈希不一致")
                if abs(inspection.duration_seconds-brief.duration_seconds) > max(2,brief.duration_seconds*.05):
                    issues.append("音频时长不符合需求单")
                if not ledger.is_stage_approved("audio",av,inspection.sha256,comp_hash):
                    issues.append("音频审核版本、内容哈希或编曲哈希不匹配")
            else:
                missing.append("缺失有效音频文件 audio.wav")
            comp.audio_metadata.file_path = "audio.wav"
            atomic_write(staging/"composition.json", comp.model_dump_json(indent=2))
        else:
            missing.extend(["缺失或损坏 composition.json","缺失有效音频文件 audio.wav"])

        cover = None
        if brief.cover_placeholder_path:
            try:
                with Image.open(brief.cover_placeholder_path) as image:
                    image.verify()
                with Image.open(brief.cover_placeholder_path) as image:
                    image.convert("RGB").save(staging/"cover.png",format="PNG")
                cover = checksum("cover.png")
            except (OSError,ValueError):
                missing.append("封面图缺失或无效 cover.png")
        else:
            missing.append("缺失封面图 cover.png")

        if not ledger.get_latest_record("lyrics") or not ledger.get_latest_record("audio"):
            missing.append("缺少完整人工审核记录")
        atomic_write(staging/"approvals.json",ledger.model_dump_json(indent=2))
        atomic_write(staging/"brief.json",brief_raw_content)
        if not brief.copyright_statement or not brief.rights_confirmed:
            missing.append("缺少经人工确认的版权声明")
        if not brief.artist_name:
            missing.append("缺少艺人或项目署名 artist_name")
        is_mock = any(artifact_provenance(item, stage).mode == "mock"
                      for item, stage in ((lyrics, "lyrics"), (composition, "audio")))
        title = lyrics.title if lyrics else brief.project_id
        atomic_write(staging/"README.md", f"# {title}\n\n项目：{brief.project_id}\n包版本：{version}\n"
            f"来源：{'离线演示合成（非真实歌曲模型）' if is_mock else '配置的音乐模型'}\n"
            "请按 manifest.json 验证所有文件。仅供本地下游交付，不调用发行平台。\n")
        manifest = Manifest(project_id=brief.project_id,song_title=title,
            artist_name=brief.artist_name or "",package_status="needs_info" if missing or issues else "ready",
            package_version=version,brief_hash=calculate_content_sha256(brief_raw_content),
            lyrics_version=lv,composition_version=av,audio_version=av,
            copyright_statement=brief.copyright_statement or "",lyrics_file=checksum("lyrics.md"),
            composition_file=checksum("composition.json"),audio_file=audio,cover_file=cover,
            approvals_file=checksum("approvals.json"),
            lyrics_approval_record=ledger.get_latest_record("lyrics"),
            audio_approval_record=ledger.get_latest_record("audio"),
            additional_files=[checksum(name) for name in ("brief.json","README.md","lyrics.json","composition-source.json") if (staging/name).exists()],
            missing_materials=missing,integrity_issues=issues,is_mock=is_mock)
        atomic_write(staging/"manifest.json",manifest.model_dump_json(indent=2))
        try:
            self.verify_package(str(staging),brief.project_id,require_ready=False)
            os.rename(staging,final)
        except Exception:
            # Keep incomplete staging for diagnostics; it is never a delivered package.
            raise
        return manifest,str(final)

    def verify_package(self, package_dir, project_id, require_ready=False):
        directory = Path(package_dir).resolve()
        manifest = Manifest.model_validate_json((directory/"manifest.json").read_text(encoding="utf-8"))
        if manifest.project_id != project_id:
            raise WorkflowGateViolationError("发行包项目不匹配")
        if require_ready and manifest.package_status != "ready":
            raise WorkflowGateViolationError("发行包仍需补充物料")
        checks = [manifest.lyrics_file,manifest.audio_file,manifest.composition_file,
                  manifest.approvals_file,*manifest.additional_files]
        if manifest.cover_file:
            checks.append(manifest.cover_file)
        for item in checks:
            path = (directory/item.relative_path).resolve()
            if path.parent != directory:
                raise WorkflowGateViolationError("发行包包含非法物料路径")
            if item.exists and (not path.is_file() or path.stat().st_size != item.size_bytes or
                                calculate_sha256(str(path)) != item.sha256):
                raise WorkflowGateViolationError(f"发行包校验失败：{item.file_name}")
        if manifest.package_status == "ready":
            if manifest.missing_materials or manifest.integrity_issues or not all(i.exists for i in checks):
                raise WorkflowGateViolationError("ready 发行包存在缺失或异常")
            if not manifest.cover_file or not manifest.copyright_statement:
                raise WorkflowGateViolationError("ready 发行包不完整")
            try:
                packaged_brief = Brief.model_validate_json((directory/"brief.json").read_text(encoding="utf-8"))
                if (packaged_brief.project_id != project_id or not packaged_brief.rights_confirmed or
                    packaged_brief.artist_name != manifest.artist_name or
                    packaged_brief.copyright_statement != manifest.copyright_statement or
                    calculate_sha256(str(directory/"brief.json")) != manifest.brief_hash):
                    raise ValueError("版权声明、署名或需求单哈希不匹配")
                source_lyrics = Lyrics.model_validate_json((directory/"lyrics.json").read_text(encoding="utf-8"))
                source_comp = Composition.model_validate_json((directory/"composition-source.json").read_text(encoding="utf-8"))
                exported_comp = Composition.model_validate_json((directory/"composition.json").read_text(encoding="utf-8"))
                ledger = ApprovalLedger.model_validate_json((directory/"approvals.json").read_text(encoding="utf-8"))
                lyrics_hash = calculate_sha256(str(directory/"lyrics.json"))
                comp_hash = calculate_sha256(str(directory/"composition-source.json"))
                if (source_lyrics.project_id != project_id or source_comp.project_id != project_id or
                    ledger.project_id != project_id or source_lyrics.version != manifest.lyrics_version or
                    source_comp.composition_version != manifest.audio_version or
                    source_comp.lyrics_version != manifest.lyrics_version or source_comp.lyrics_sha256 != lyrics_hash):
                    raise ValueError("物料项目或版本不一致")
                if not ledger.is_stage_approved("lyrics",manifest.lyrics_version,lyrics_hash):
                    raise ValueError("歌词审核不匹配")
                if not ledger.is_stage_approved("audio",manifest.audio_version,manifest.audio_file.sha256,comp_hash):
                    raise ValueError("音频审核不匹配")
                if (directory/"lyrics.md").read_text(encoding="utf-8") != source_lyrics.to_markdown():
                    raise ValueError("展示歌词与审核源文件不匹配")
                normalized = source_comp.model_copy(deep=True)
                normalized.audio_metadata.file_path = "audio.wav"
                if normalized != exported_comp:
                    raise ValueError("导出编曲与审核源文件不匹配")
                qc = inspect_acoustic_quality(str(directory/"audio.wav"))
                if (not qc.is_valid or qc.sha256 != source_comp.audio_metadata.sha256 or
                    abs(qc.duration_seconds-packaged_brief.duration_seconds)>max(2,packaged_brief.duration_seconds*.05)):
                    raise ValueError("发行音频未通过检查")
                if manifest.is_mock != any(artifact_provenance(item, stage).mode == "mock"
                        for item, stage in ((source_lyrics, "lyrics"), (source_comp, "audio"))):
                    raise ValueError("音频来源标记不匹配")
                if (manifest.lyrics_approval_record != ledger.get_latest_record("lyrics") or
                    manifest.audio_approval_record != ledger.get_latest_record("audio")):
                    raise ValueError("清单审核快照与账本不一致")
            except (OSError,ValueError) as exc:
                raise WorkflowGateViolationError(f"ready 发行包审核验证失败：{exc}") from exc
        return manifest
