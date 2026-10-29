"""Durable workflow transaction contracts."""
from typing import List, Optional, Literal
from uuid import uuid4
from pydantic import Field
from src.models.common import Contract, ExecutionEvent, utc_now
from src.models.brief import BriefAnomaly, Brief
from src.models.approval import ApprovalLedger
from src.core.state_machine import ProjectState

class PendingOperation(Contract):
    operation_id: str = Field(default_factory=lambda: uuid4().hex)
    stage: Literal["lyrics", "audio", "package"]
    version: str = Field(pattern=r"^v[1-9][0-9]*$")
    feedback: Optional[str] = None
    task_id: Optional[str] = None
    result_sha256: Optional[str] = None
    result_related_sha256: Optional[str] = None
    target_dir: Optional[str] = None
    started_at: str = Field(default_factory=utc_now)

class ProjectCheckpoint(Contract):
    project_id: str
    state: ProjectState
    schema_version: int = 2
    lyrics_version: str = "v1"
    audio_version: str = "v1"
    composition_version: str = "v1"
    completed_stages: List[str] = Field(default_factory=list)
    detected_anomalies: List[BriefAnomaly] = Field(default_factory=list)
    brief_hash: Optional[str] = None
    brief_snapshot: Optional[Brief] = None
    brief_mirror_pending: bool = False
    approvals: Optional[ApprovalLedger] = None
    pending: Optional[PendingOperation] = None
    package_dir: Optional[str] = None
    package_version: Optional[str] = None
    events: List[ExecutionEvent] = Field(default_factory=list)
    last_error: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

class MusicGraphState(Contract):
    project_id: str

class MusicTaskResult(Contract):
    provider: str
    task_id: str
    status: str = "completed"
    audio_path: str

class MusicTaskResponse(Contract):
    task_id: Optional[str] = None
    id: Optional[str] = None
    status: Optional[str] = None
    audio_url: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None
    data: Optional['MusicTaskResponse'] = None

MusicTaskResponse.model_rebuild()
