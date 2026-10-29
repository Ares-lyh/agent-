"""Brief Model and Anomaly Detection."""
from typing import List, Optional, Tuple
import re
from pydantic import BaseModel, Field, model_validator
from src.models.common import Contract
from src.models.vocals import VocalRequirements


class BriefAnomaly(Contract):
    field: str
    issue_type: str  # e.g., "conflict", "missing", "inconsistency"
    message: str
    severity: str = "warning"  # "warning" or "blocking"


class Brief(Contract):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    artist_name: Optional[str] = None
    copyright_statement: Optional[str] = None
    rights_confirmed: bool = False
    theme: str = Field(min_length=1)
    genre: str
    mood: str
    duration_seconds: int = Field(gt=0)
    duration_text: Optional[str] = None
    audience: Optional[str] = None
    platform: List[str] = Field(default_factory=list)
    primary_platform: Optional[str] = None
    references: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    lyrics_language: str = "中文"
    allow_sampling: bool = False
    vocals: Optional[VocalRequirements] = None
    cover_placeholder_path: Optional[str] = None

    def parse_duration_text(self) -> Optional[int]:
        """Parse duration text like '3分30秒', '3分钟', '2分45秒' to seconds."""
        if not self.duration_text:
            return None
        text = self.duration_text.strip()
        
        # Match 'X分Y秒' or 'X分钟Y秒' or 'XmYs'
        match = re.match(r'(?:(\d+)\s*(?:分钟|分|m))?\s*(?:(\d+)\s*(?:秒|s))?', text)
        if match:
            minutes = int(match.group(1)) if match.group(1) else 0
            seconds = int(match.group(2)) if match.group(2) else 0
            if minutes > 0 or seconds > 0:
                return minutes * 60 + seconds
        return None

    def detect_anomalies(self) -> List[BriefAnomaly]:
        """Detect conflicts, inconsistencies, and missing fields."""
        anomalies: List[BriefAnomaly] = []

        # 1. Check duration_seconds vs duration_text conflict
        if self.duration_text:
            parsed_seconds = self.parse_duration_text()
            if parsed_seconds is not None and parsed_seconds != self.duration_seconds:
                anomalies.append(
                    BriefAnomaly(
                        field="duration",
                        issue_type="conflict",
                        message=(
                            f"数值与文本冲突: duration_seconds ({self.duration_seconds}s) "
                            f"与 duration_text ('{self.duration_text}' = {parsed_seconds}s) 不一致"
                        ),
                        severity="warning",
                    )
                )

        # 2. Check primary_platform in platform list
        if self.primary_platform and self.platform:
            if self.primary_platform not in self.platform:
                anomalies.append(
                    BriefAnomaly(
                        field="primary_platform",
                        issue_type="inconsistency",
                        message=(
                            f"主平台冲突: primary_platform ('{self.primary_platform}') "
                            f"不在 platform 列表 {self.platform} 中"
                        ),
                        severity="warning",
                    )
                )

        # 3. Check cover placeholder path
        if not self.cover_placeholder_path:
            anomalies.append(
                BriefAnomaly(
                    field="cover_placeholder_path",
                    issue_type="missing",
                    message="缺少封面占位图路径 cover_placeholder_path，最终物料包将判定为 package_needs_info",
                    severity="blocking_package",
                )
            )

        return anomalies
