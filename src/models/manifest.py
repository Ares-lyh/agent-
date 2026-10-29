"""Release Package Manifest Schema and Integrity Validation."""
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field
from src.models.common import Contract
from src.models.approval import ApprovalRecord


class FileChecksum(Contract):
    file_name: str
    relative_path: str
    sha256: str
    size_bytes: int
    exists: bool = True


class AudioFileChecksum(Contract):
    file_name: str = "audio.wav"
    relative_path: str = "audio.wav"
    format: str = "wav"
    duration_seconds: float
    sample_rate: int
    channels: int
    bit_depth: int
    sha256: str
    size_bytes: int
    exists: bool = True


class Manifest(Contract):
    project_id: str
    song_title: str
    artist_name: str
    package_status: Literal["ready", "needs_info"] = Field(description="物料包状态: ready 或 needs_info")
    package_version: str = "v1"
    brief_hash: str = Field(description="原始 brief 文件的 SHA-256")
    lyrics_version: str
    composition_version: str
    audio_version: str
    copyright_statement: str = Field(description="版权与原创声明")
    
    # Files and hashes
    lyrics_file: FileChecksum
    audio_file: AudioFileChecksum
    cover_file: Optional[FileChecksum] = None
    approvals_file: FileChecksum
    composition_file: FileChecksum
    
    additional_files: List[FileChecksum] = Field(default_factory=list)
    is_mock: bool = False

    # Audit trail
    lyrics_approval_record: Optional[ApprovalRecord] = None
    audio_approval_record: Optional[ApprovalRecord] = None
    
    # Gate audit
    missing_materials: List[str] = Field(default_factory=list, description="缺失的关键物料列表")
    integrity_issues: List[str] = Field(default_factory=list, description="哈希或文件格式不一致记录")
    
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
