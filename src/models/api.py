"""Public HTTP contracts; no unvalidated business dictionaries cross the API."""
from typing import List, Optional, Dict, Literal
from pydantic import Field
from src.models.common import Contract
from src.models.brief import Brief, BriefAnomaly
from src.models.lyrics import Lyrics
from src.models.composition import Composition
from src.models.plan import TaskPlan
from src.models.approval import ApprovalRecord
from src.models.workflow import ProjectCheckpoint
from src.models.manifest import Manifest
from src.models.report import RunReport
from src.models.provenance import ArtifactProvenance
from src.models.vocals import VocalRequirements


class ProviderStatus(Contract):
    mode: Literal["real", "mock", "unconfigured"]
    provider: str
    model: Optional[str] = None
    configured: bool


class RuntimeStatus(Contract):
    text: ProviderStatus
    music: ProviderStatus
    production_ready: bool
    message: str


class ProjectProgress(Contract):
    project_id: str
    state: str
    execution_status: Literal["queued", "running", "failed", "interrupted", "idle"]
    phase: Literal["plan", "lyrics", "audio", "package", "review"]
    message: str
    last_error: Optional[str] = None
    updated_at: str

class ApprovalRequest(Contract):
    stage: Literal["lyrics","audio"]
    approved: bool
    feedback: Optional[str] = None
    reviewer: Optional[str] = "Web Studio Reviewer"

class ExportRequest(Contract):
    target_dir: Optional[str] = None

class CreateProjectRequest(Contract):
    brief: Brief

class RightsRequest(Contract):
    artist_name: str = Field(min_length=1)
    copyright_statement: str = Field(min_length=1)
    rights_confirmed: bool

class ActionResponse(Contract):
    success: bool = True
    project_id: Optional[str] = None
    state: Optional[str] = None
    message: str = ""
    cover_url: Optional[str] = None
    duration: Optional[float] = None
    sha256: Optional[str] = None
    lyrics_title: Optional[str] = None
    anomalies: List[BriefAnomaly] = Field(default_factory=list)
    package_status: Optional[str] = None
    package_dir: Optional[str] = None
    manifest: Optional[Manifest] = None

class ProjectSummary(Contract):
    project_id: str
    title: str
    genre: str
    state: str
    lyrics_version: str
    audio_version: str
    completed_stages: List[str]
    updated_at: str
    lyrics_source: ArtifactProvenance
    audio_source: ArtifactProvenance

class LyricsSummary(Contract):
    version: str
    title: str

class ProjectDetail(Contract):
    project_id: str
    checkpoint: ProjectCheckpoint
    brief: Brief
    plan: Optional[TaskPlan] = None
    lyrics: Optional[Lyrics] = None
    lyrics_history: List[LyricsSummary] = Field(default_factory=list)
    all_lyrics: Dict[str,Lyrics] = Field(default_factory=dict)
    composition: Optional[Composition] = None
    approvals: List[ApprovalRecord] = Field(default_factory=list)
    has_audio: bool = False
    audio_url: Optional[str] = None
    cover_url: Optional[str] = None
    manifest: Optional[Manifest] = None
    download_audio_url: Optional[str] = None
    download_package_url: Optional[str] = None
    lyrics_source: ArtifactProvenance
    audio_source: ArtifactProvenance
    requested_vocals: VocalRequirements

class FixtureBrief(Contract):
    file_name: str
    project_id: str
    theme: str
    genre: str
    brief: Brief


class ReportResponse(Contract):
    project_id: str
    markdown: str
    json_report: RunReport = Field(alias="json")
