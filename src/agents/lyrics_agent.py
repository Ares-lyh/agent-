"""Lyrics generation with bounded meter reflection and immutable versions."""
from pathlib import Path
from src.agents.base import BaseAgent
from src.models.brief import Brief
from src.models.lyrics import Lyrics
from src.services.llm_service import LLMService
from src.tools.rhyme_tool import analyze_rhyme_and_meter
from src.utils.persistence import atomic_write, next_version, publish, project_lock
from src.config import settings

class LyricsAgent(BaseAgent):
    def __init__(self, llm_service=None):
        super().__init__("LyricsAgent")
        self.llm_service = llm_service or LLMService()

    def generate(self, project_dir, brief, version="v1", feedback=None, reserved=False):
        folder = Path(project_dir) / "lyrics"
        folder.mkdir(parents=True, exist_ok=True)
        # Workflow callers already hold the cross-process project lock.
        if not reserved:
            with project_lock(folder):
                version = next_version(folder, version)
                return self.generate(project_dir, brief, version, feedback, reserved=True)
        path = folder / f"{version}.json"
        if path.exists():
            raise FileExistsError(f"禁止覆盖历史歌词 {version}")
        revision_feedback = feedback
        if feedback:
            prior = [p for p in folder.glob("v*.json") if int(p.stem[1:]) < int(version[1:])]
            if prior:
                previous = Lyrics.model_validate_json(max(prior,key=lambda p:int(p.stem[1:])).read_text(encoding="utf-8"))
                revision_feedback += "\n请针对上一版本修改，保持未要求改动的意图：\n" + previous.to_markdown()
        for attempt in range(settings.LYRICS_MAX_REVISIONS + 1):
            lyrics = self.llm_service.generate_lyrics(brief, version, revision_feedback)
            if lyrics.project_id != brief.project_id or lyrics.version != version:
                raise ValueError("歌词项目/版本不匹配")
            analysis = analyze_rhyme_and_meter([line for section in lyrics.sections for line in section.lines])
            strict_meter = any(word in " ".join(brief.constraints) for word in ("七言", "五言", "押韵严格", "严格押韵"))
            bad_meter = analysis.meter_regularity < .6
            if "七言" in " ".join(brief.constraints):
                bad_meter = any(stat.char_count != 7 for stat in analysis.line_stats)
            if "五言" in " ".join(brief.constraints):
                bad_meter = any(stat.char_count != 5 for stat in analysis.line_stats)
            known = [stat for stat in analysis.line_stats if stat.rhyme_vowel]
            bad_rhyme = strict_meter and (len(known) < len(analysis.line_stats) or
                        not any(len(group) >= 2 for group in analysis.detected_rhymes.values()))
            if not bad_meter and not bad_rhyme:
                break
            if attempt == settings.LYRICS_MAX_REVISIONS:
                if strict_meter:
                    raise ValueError("歌词未通过指定格律/押韵要求，请调整需求或继续修改")
                break
            revision_feedback = (feedback or "") + "\n请根据词律工具修正上一稿：" + "; ".join(analysis.feedback_notes)
            revision_feedback += "\n上一稿：\n" + lyrics.to_markdown()
        lyrics.raw_response_summary += (f" [词律自检] {analysis.rhyme_scheme}; "
            f"节拍整齐度={analysis.meter_regularity}; 修订轮数={attempt}; "
            + "; ".join(analysis.feedback_notes))
        temporary = folder / f".{version}.json.part"
        atomic_write(temporary, lyrics.model_dump_json(indent=2))
        publish(temporary, path)
        return lyrics
