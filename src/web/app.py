"""Local music studio HTTP interface using the same workflow gates as CLI."""
import io
import zipfile
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional, Literal
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from src.models.api import (ApprovalRequest, ExportRequest, CreateProjectRequest,
    RightsRequest, ActionResponse, ProjectSummary, ProjectDetail, LyricsSummary, FixtureBrief, ReportResponse,
    RuntimeStatus, ProviderStatus, ProjectProgress)
from src.models.lyrics import Lyrics
from src.models.composition import Composition
from src.models.plan import TaskPlan
from src.models.manifest import Manifest
from src.models.common import ExecutionEvent
from src.agents.master_agent import MasterAgent
from src.core.checkpoint import CheckpointManager
from src.core.state_machine import ProjectState, StateMachine
from src.core.exceptions import MusicAgentException
from src.utils.persistence import atomic_write, project_lock
from src.utils.cover_utils import generate_cyberpunk_cover
from src.utils.hash_utils import calculate_sha256
from src.config import settings
from src.services.provenance import artifact_provenance
from src.services.vocal_direction import resolve_vocals
from src.web.jobs import studio_jobs

app = FastAPI(title="沿长科技 · 音乐创作工作台",version="2.0.0")
master = MasterAgent()
ckpt_mgr = master.checkpoint_manager
STATIC_DIR = Path(__file__).parent/"static"


@app.get("/api/runtime", response_model=RuntimeStatus)
def runtime_status():
    text = master.llm_service
    music = master.audio_agent.client
    music_configured = False
    if not getattr(music, "is_mock", True):
        try:
            music.validate_configuration()
            music_configured = True
        except ValueError:
            pass
    ready = not text.use_mock and bool(text.api_key) and music_configured
    return RuntimeStatus(
        text=ProviderStatus(mode="mock" if text.use_mock else "real" if text.api_key else "unconfigured",
            provider="configured-text-api", model=text.model, configured=bool(text.api_key) and not text.use_mock),
        music=ProviderStatus(mode="mock" if getattr(music, "is_mock", True) else "real" if music_configured else "unconfigured",
            provider=getattr(music, "provider", "mock"), model=getattr(music, "model", None), configured=music_configured),
        production_ready=ready,
        message="真实服务已配置；连接结果以实际调用为准" if ready else "真实创作需要配置文本和音乐服务，并关闭演示模式")


@app.get("/api/projects/{project_id}/progress", response_model=ProjectProgress)
def project_progress(project_id):
    directory(project_id)
    cp = master.graph_engine.load(project_id)
    status = studio_jobs.status(project_id)
    if status == "failed" and not cp.last_error:
        status = None  # A CLI resume may have completed the previous failed worker.
    if status not in ("running", "queued", "failed"):
        status = "failed" if cp.last_error else "interrupted" if cp.pending else "idle"
    phase = ("plan" if cp.pending and cp.pending.stage == "lyrics" and "plan_generation" not in cp.completed_stages
             else cp.pending.stage if cp.pending else
             "audio" if status in ("running", "queued") and cp.state == ProjectState.LYRICS_APPROVED else
             "package" if status in ("running", "queued") and cp.state == ProjectState.AUDIO_APPROVED else "review")
    labels = {"plan": "主 Agent 正在规划制作任务", "lyrics": "作词 Agent 正在创作和检查歌词",
              "audio": "音频 Agent 正在编曲并调用音乐服务", "package": "正在校验并构建本地物料包",
              "review": "等待人工审核"}
    message = (labels[phase] if status in ("queued", "running") else
               cp.last_error or ("任务中断，请恢复原任务" if status == "interrupted" else labels[phase]))
    return ProjectProgress(project_id=project_id, state=cp.state.value, execution_status=status,
        phase=phase, message=message, last_error=cp.last_error, updated_at=cp.updated_at)


@app.post("/api/projects/start", response_model=ProjectProgress, status_code=202)
def start_project(req: CreateProjectRequest):
    if not runtime_status().production_ready:
        raise HTTPException(409, runtime_status().message)
    # Always check the Brief even if another worker is active for this ID.
    from src.core.graph import brief_digest
    if ckpt_mgr.project_exists(req.brief.project_id):
        existing = master.graph_engine.load(req.brief.project_id)
        if (existing.brief_hash or brief_digest(master._load_brief(req.brief.project_id))) != brief_digest(req.brief):
            raise HTTPException(409, "同一项目 ID 的需求单已改变；请生成新项目 ID")
    studio_jobs.submit(req.brief.project_id,
        lambda: master.graph_engine.prepare_start(req.brief), lambda: master.start(req.brief))
    return project_progress(req.brief.project_id)


@app.post("/api/projects/{project_id}/execute", response_model=ProjectProgress, status_code=202)
def execute_project(project_id):
    directory(project_id)
    if not runtime_status().production_ready:
        raise HTTPException(409, runtime_status().message)
    # Resume respects both review gates; it never signs a human approval.
    studio_jobs.submit(project_id, lambda: None, lambda: master.resume(project_id))
    return project_progress(project_id)

@app.exception_handler(MusicAgentException)
async def workflow_error(request, exc):
    return JSONResponse(status_code=409,content={"detail":str(exc)})

def directory(project_id):
    if not ckpt_mgr.project_exists(project_id):
        raise HTTPException(404,"项目不存在")
    return Path(ckpt_mgr.get_project_dir(project_id))

def load_optional(model,path):
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        return None

@app.get("/api/projects",response_model=List[ProjectSummary])
def list_projects():
    rows=[]
    for folder in Path(ckpt_mgr.base_storage_dir).iterdir():
        if not folder.is_dir() or not (folder/"checkpoint.json").is_file():
            continue
        try:
            cp=master.graph_engine.load(folder.name)
            brief=master._load_brief(folder.name)
            lyrics=load_optional(Lyrics,folder/"lyrics"/f"{cp.lyrics_version}.json")
            composition=load_optional(Composition,folder/"audio"/f"{cp.composition_version}_comp.json")
            rows.append(ProjectSummary(project_id=folder.name,title=lyrics.title if lyrics else folder.name,
                genre=brief.genre,state=cp.state.value,lyrics_version=cp.lyrics_version,
                audio_version=cp.audio_version,completed_stages=cp.completed_stages,updated_at=cp.updated_at,
                lyrics_source=artifact_provenance(lyrics,"lyrics"), audio_source=artifact_provenance(composition,"audio")))
        except (OSError,ValueError,MusicAgentException):
            continue
    return sorted(rows,key=lambda r:r.updated_at,reverse=True)

@app.get("/api/projects/{project_id}",response_model=ProjectDetail)
def get_project_detail(project_id):
    folder=directory(project_id)
    cp=master.graph_engine.load(project_id)
    brief=master._load_brief(project_id)
    history={}
    for path in sorted((folder/"lyrics").glob("v*.json"),key=lambda p:int(p.stem[1:])):
        lyrics=load_optional(Lyrics,path)
        if lyrics:
            history[lyrics.version]=lyrics
    audio=folder/"audio"/f"{cp.audio_version}_audio.wav"
    manifest=load_optional(Manifest,Path(cp.package_dir)/"manifest.json") if cp.package_dir else None
    composition=load_optional(Composition,folder/"audio"/f"{cp.composition_version}_comp.json")
    return ProjectDetail(project_id=project_id,checkpoint=cp,brief=brief,
        plan=load_optional(TaskPlan,folder/"plan.json"),lyrics=history.get(cp.lyrics_version),
        lyrics_history=[LyricsSummary(version=l.version,title=l.title) for l in history.values()],
        all_lyrics=history,composition=composition,
        approvals=cp.approvals.records,has_audio=audio.is_file(),
        audio_url=f"/api/projects/{project_id}/audio?v={cp.audio_version}" if audio.is_file() else None,
        cover_url=f"/api/projects/{project_id}/cover" if brief.cover_placeholder_path else None,
        manifest=manifest,download_audio_url=f"/api/projects/{project_id}/download/audio" if audio.is_file() else None,
        download_package_url=f"/api/projects/{project_id}/download/package" if cp.package_dir else None,
        lyrics_source=artifact_provenance(history.get(cp.lyrics_version),"lyrics"),
        audio_source=artifact_provenance(composition,"audio"),
        requested_vocals=resolve_vocals(brief, cp.pending.feedback if cp.pending and cp.pending.stage == "audio" else None))

@app.get("/api/projects/{project_id}/audio")
@app.get("/api/projects/{project_id}/download/audio")
def stream_audio(project_id):
    folder=directory(project_id); cp=master.graph_engine.load(project_id)
    path=folder/"audio"/f"{cp.audio_version}_audio.wav"
    if not path.is_file():
        raise HTTPException(404,"音频尚未生成")
    return FileResponse(path,media_type="audio/wav",filename=f"{project_id}_{cp.audio_version}.wav")

@app.get("/api/projects/{project_id}/download/lyrics")
def download_lyrics(project_id,format:Literal["txt","lrc","json"]="txt"):
    folder=directory(project_id); cp=master.graph_engine.load(project_id)
    lyrics=load_optional(Lyrics,folder/"lyrics"/f"{cp.lyrics_version}.json")
    if not lyrics:
        raise HTTPException(404,"歌词尚未生成")
    if format=="lrc":
        raise HTTPException(409,"当前没有模型提供的逐句对齐时间戳，请下载 TXT 或 JSON")
    content=lyrics.model_dump_json(indent=2) if format=="json" else lyrics.to_markdown()
    return Response(content,media_type="application/json" if format=="json" else "text/plain",
        headers={"Content-Disposition":f"attachment; filename={project_id}_lyrics.{format}"})

@app.get("/api/projects/{project_id}/download/package")
def download_package(project_id):
    folder=directory(project_id)
    with project_lock(folder):
        cp=master.graph_engine.load(project_id)
        StateMachine.assert_audio_approved(cp.state,project_id)
        if not cp.package_dir:
            raise HTTPException(409,"请先构建发行物料包")
        try:
            master.packager.verify_package(cp.package_dir,project_id)
        except Exception:
            cp.state=ProjectState.PACKAGE_NEEDS_INFO
            cp.last_error="发行包文件被修改或缺失，请重新校验封包"
            master.graph_engine.save(cp)
            raise HTTPException(409,cp.last_error)
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(Path(cp.package_dir).iterdir()):
                if path.is_file():
                    archive.write(path,path.name)
        return Response(buffer.getvalue(),media_type="application/zip",
            headers={"Content-Disposition":f"attachment; filename={project_id}_{cp.package_version}.zip"})

@app.get("/api/projects/{project_id}/cover")
def get_cover_image(project_id):
    directory(project_id)
    brief=master._load_brief(project_id)
    if not brief.cover_placeholder_path or not Path(brief.cover_placeholder_path).is_file():
        raise HTTPException(404,"封面不存在")
    return FileResponse(brief.cover_placeholder_path,media_type="image/png")

def store_cover(project_id,content):
    folder=directory(project_id)
    with project_lock(folder):
        brief=master._load_brief(project_id)
        # Validate before writing and normalize the actual format to PNG.
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                output=io.BytesIO(); image.convert("RGB").save(output,format="PNG")
        except (OSError,ValueError):
            raise HTTPException(422,"请上传可解析的图片")
        cp=master.graph_engine.load(project_id)
        path=folder/("cover_"+calculate_sha256_bytes(output.getvalue())[:16]+".png")
        atomic_write(path,output.getvalue())
        brief.cover_placeholder_path=str(path.resolve())
        master.graph_engine.update_metadata(project_id,brief,"COVER","已验证并保存新封面")
    return ActionResponse(cover_url=f"/api/projects/{project_id}/cover",message="封面已保存，请重新校验封包")

def calculate_sha256_bytes(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()

@app.post("/api/projects/{project_id}/cover/upload",response_model=ActionResponse)
async def upload_project_cover(project_id,file:UploadFile=File(...)):
    content=await file.read(20*1024*1024+1)
    if len(content)>20*1024*1024:
        raise HTTPException(413,"封面不得超过 20 MB")
    return store_cover(project_id,content)

@app.post("/api/projects/{project_id}/cover/generate",response_model=ActionResponse)
def generate_project_cover(project_id):
    folder=directory(project_id); brief=master._load_brief(project_id)
    temporary=folder/".cover_draft.png"
    generate_cyberpunk_cover(title=brief.theme,project_id=project_id,genre=brief.genre,output_path=str(temporary))
    try:
        return store_cover(project_id,temporary.read_bytes())
    finally:
        temporary.unlink(missing_ok=True)

@app.post("/api/projects/{project_id}/audio/generate_full",response_model=ActionResponse)
def generate_full_audio(project_id,duration:Optional[float]=Query(None,gt=0)):
    directory(project_id); brief=master._load_brief(project_id)
    if duration is not None and abs(duration-brief.duration_seconds)>.1:
        raise HTTPException(422,"时长与需求单不同，请以新需求创建项目")
    cp=master.graph_engine.load(project_id)
    if cp.state==ProjectState.LYRICS_APPROVED:
        cp,message=master.resume(project_id)
    else:
        cp=master.approve_stage(project_id,"audio",False,feedback="按需求时长重新生成完整音频")
    comp=master._load_latest_composition(project_id,cp.composition_version)
    return ActionResponse(project_id=project_id,state=cp.state.value,duration=comp.audio_metadata.duration_seconds,
        sha256=comp.audio_metadata.sha256,message="新版本音频已生成，请重新试听审核")

@app.post("/api/projects/{project_id}/approve",response_model=ActionResponse)
def approve_stage(project_id,req:ApprovalRequest):
    directory(project_id)
    if studio_jobs.status(project_id) in ("running", "queued"):
        raise HTTPException(409, "创作任务仍在运行，请等待生成完成后审核")
    cp=master.approve_stage(project_id,req.stage,req.approved,req.reviewer or "Web Reviewer",req.feedback)
    return ActionResponse(project_id=project_id,state=cp.state.value,message="审核操作完成")

@app.post("/api/projects/{project_id}/resume",response_model=ActionResponse)
def resume_pipeline(project_id):
    directory(project_id); cp,message=master.resume(project_id)
    return ActionResponse(project_id=project_id,state=cp.state.value,message=message)

@app.post("/api/projects/{project_id}/export",response_model=ActionResponse)
def export_package(project_id,req:ExportRequest):
    directory(project_id); manifest,path=master.export_package(project_id,req.target_dir)
    return ActionResponse(project_id=project_id,package_status=manifest.package_status,
                          package_dir=path,manifest=manifest,message="物料包已构建")

@app.post("/api/projects/{project_id}/rights",response_model=ActionResponse)
def update_rights(project_id,req:RightsRequest):
    folder=directory(project_id)
    with project_lock(folder):
        brief=master._load_brief(project_id)
        brief.artist_name=req.artist_name
        brief.copyright_statement=req.copyright_statement
        brief.rights_confirmed=req.rights_confirmed
        master.graph_engine.update_metadata(project_id,brief,"RIGHTS","已确认版权声明和署名")
    return ActionResponse(message="署名和版权信息已保存，请重新校验封包")

@app.post("/api/projects/{project_id}/brief/auto-fix", response_model=ActionResponse)
def auto_fix_brief(project_id: str):
    folder = directory(project_id)
    with project_lock(folder):
        brief = master._load_brief(project_id)
        fixed_actions = []
        if brief.duration_text:
            parsed = brief.parse_duration_text()
            if parsed is not None and parsed != brief.duration_seconds:
                m = brief.duration_seconds // 60
                s = brief.duration_seconds % 60
                brief.duration_text = f"{m}分{s}秒" if s else f"{m}分钟"
                fixed_actions.append(f"时长展示对齐为 {brief.duration_text}")
        if brief.primary_platform and brief.platform:
            if brief.primary_platform not in brief.platform:
                brief.platform.append(brief.primary_platform)
                fixed_actions.append(f"追加主平台 {brief.primary_platform} 到目标平台列表")
        if not brief.cover_placeholder_path or not Path(brief.cover_placeholder_path).is_file():
            cover_path = folder / "cover_autofix.png"
            generate_cyberpunk_cover(title=brief.theme, project_id=project_id, genre=brief.genre, output_path=str(cover_path))
            brief.cover_placeholder_path = str(cover_path.resolve())
            fixed_actions.append("已自动生成并绑定 Cyberpunk 风格封面")

        message = "；".join(fixed_actions) if fixed_actions else "需求单已完全合规，无需自动修复"
        master.graph_engine.update_metadata(project_id, brief, "AUTO_FIX", message)
    return ActionResponse(project_id=project_id, message=message)

@app.post("/api/projects/create",response_model=ActionResponse)
def create_project(req:CreateProjectRequest):
    cp,plan,lyrics=master.start(req.brief)
    return ActionResponse(project_id=cp.project_id,state=cp.state.value,lyrics_title=lyrics.title,
                          anomalies=cp.detected_anomalies)

@app.get("/api/fixtures/briefs",response_model=List[FixtureBrief])
def list_fixture_briefs():
    from src.models.brief import Brief
    return [FixtureBrief(file_name=path.name,**{key:getattr(brief,key) for key in
            ("project_id","theme","genre")},brief=brief)
            for path in sorted(Path("fixtures/briefs").glob("*.json"))
            for brief in [Brief.model_validate_json(path.read_text(encoding="utf-8"))]]

@app.get("/api/projects/{project_id}/report",response_model=ReportResponse)
def get_run_report(project_id):
    directory(project_id)
    report=master.generate_report(project_id)
    return ReportResponse(project_id=project_id,markdown=report.to_markdown(),json=report)

@app.exception_handler(ValueError)
async def validation_error(request,exc):
    return JSONResponse(status_code=422,content={"detail":str(exc)})

@app.exception_handler(RuntimeError)
async def runtime_error(request,exc):
    return JSONResponse(status_code=502,content={"detail":str(exc)})

app.mount("/static",StaticFiles(directory=str(STATIC_DIR)),name="static")

@app.get("/")
def index():
    return FileResponse(STATIC_DIR/"index.html", headers={"Cache-Control": "no-store"})
