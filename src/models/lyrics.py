"""Lyrics Data Models and Schema Validation."""
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from src.models.common import Contract, GenerationParameters


class LyricSection(Contract):
    section_type: str = Field(description="段落类型，如 Verse, Chorus, Bridge, Outro")
    section_name: str = Field(description="段落名称，如 主歌 1, 副歌")
    emotion_tag: str = Field(description="该段落的情绪标记，如 怀旧、激动、温暖")
    lines: List[str] = Field(min_length=1, description="段落歌词行列表")


class Lyrics(Contract):
    project_id: str
    version: str = Field(default="v1", pattern=r"^v[1-9][0-9]*$")
    title: str = Field(min_length=1, description="歌曲标题")
    sections: List[LyricSection] = Field(min_length=1, description="各段落歌词与结构")
    structure_summary: str = Field(description="段落结构摘要，如 Verse-Chorus-Verse-Chorus-Outro")
    language: str = "中文"
    deepseek_params: GenerationParameters = Field(default_factory=GenerationParameters, description="生成参数配置")
    raw_response_summary: str = Field(description="原始响应摘要或 Token 统计")
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_markdown(self) -> str:
        """Format lyrics into readable Markdown."""
        lines = [f"# {self.title}", "", f"> 结构：{self.structure_summary} | 版本：{self.version}", ""]
        for sec in self.sections:
            lines.append(f"## [{sec.section_name}] ({sec.emotion_tag})")
            for line in sec.lines:
                lines.append(line)
            lines.append("")
        return "\n".join(lines)
