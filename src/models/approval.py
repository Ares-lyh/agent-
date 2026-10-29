"""Human decisions bound to immutable project artifacts."""
import hashlib
import json
from typing import List, Optional, Literal
from pydantic import Field
from src.models.common import Contract, utc_now

class ApprovalRecord(Contract):
    stage: Literal["lyrics", "audio"]
    approved: bool
    target_version: str = Field(pattern=r"^v[1-9][0-9]*$")
    project_id: Optional[str] = None
    artifact_sha256: Optional[str] = Field(default=None,pattern=r"^[0-9a-f]{64}$")
    related_sha256: Optional[str] = Field(default=None,pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(default="Human Reviewer", min_length=1)
    feedback: Optional[str] = None
    timestamp: str = Field(default_factory=utc_now)
    signature_hash: Optional[str] = None
    def digest(self):
        payload = json.dumps(self.model_dump(exclude={"signature_hash"}), sort_keys=True,
                             ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    def seal(self):
        self.signature_hash = self.digest()
        return self

class ApprovalLedger(Contract):
    project_id: str
    records: List[ApprovalRecord] = Field(default_factory=list)
    def get_latest_record(self, stage):
        return next((r for r in reversed(self.records) if r.stage == stage), None)
    def is_stage_approved(self, stage, version=None, sha256=None, related_sha256=None):
        record = self.get_latest_record(stage)
        if not record or not record.approved:
            return False
        if version is None and sha256 is None:
            return True
        return (record.project_id == self.project_id and record.target_version == version
                and record.artifact_sha256 == sha256 and bool(sha256)
                and record.related_sha256 == related_sha256
                and record.signature_hash == record.digest())
