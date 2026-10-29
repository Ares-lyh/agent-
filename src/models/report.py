"""Run Report Generator for auditing the full lifecycle execution."""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field


from src.models.common import ExecutionEvent, Contract
from src.models.brief import BriefAnomaly
from src.models.approval import ApprovalRecord


class RunReport(Contract):
    project_id: str
    song_title: str
    genre: str
    mood: str
    current_state: str
    packaging_status: Optional[str] = None
    anomalies_detected: List[BriefAnomaly] = Field(default_factory=list)
    approvals_summary: Dict[str, ApprovalRecord] = Field(default_factory=dict)
    execution_timeline: List[ExecutionEvent] = Field(default_factory=list)
    artifact_paths: Dict[str, str] = Field(default_factory=dict)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_markdown(self) -> str:
        """Format the report into clean markdown."""
        lines = [
            f"# 音乐创作主 Agent 运行报告 - 项目: {self.project_id}",
            "",
            "## 1. 项目基本概况",
            f"- **歌曲标题**: {self.song_title}",
            f"- **曲风与情绪**: {self.genre} / {self.mood}",
            f"- **最终生命周期状态**: `{self.current_state}`",
            f"- **发行物料包状态**: `{self.packaging_status or 'N/A'}`",
            f"- **报告生成时间**: {self.generated_at}",
            "",
            "## 2. 需求单异常与冲突检测",
        ]
        if self.anomalies_detected:
            for a in self.anomalies_detected:
                lines.append(f"- **[{a.get('issue_type', '警告')}]** 字段: `{a.get('field')}` - {a.get('message')}")
        else:
            lines.append("- 未检测到任何字段冲突或缺失，需求单 100% 合规。")

        lines.extend([
            "",
            "## 3. 人工审核记录汇总",
        ])
        if self.approvals_summary:
            for stage, info in self.approvals_summary.items():
                status_str = "已批准" if info.get("approved") else "未通过/修改"
                lines.append(f"- **阶段 [{stage}]**: {status_str} | 审核人: {info.get('reviewer')} | 时间: {info.get('timestamp')}")
                if info.get("feedback"):
                    lines.append(f"  - 批注反馈: {info.get('feedback')}")
        else:
            lines.append("- 尚无已完成的人工审核记录。")

        lines.extend([
            "",
            "## 4. 产物清单与文件索引",
        ])
        for k, v in self.artifact_paths.items():
            lines.append(f"- `{k}`: {v}")

        lines.extend([
            "",
            "## 5. 执行流水线时间线 (Timeline)",
        ])
        for event in self.execution_timeline:
            lines.append(f"- `[{event.timestamp}]` **{event.stage}** - {event.action}: {event.details} ({event.status})")

        return "\n".join(lines)
