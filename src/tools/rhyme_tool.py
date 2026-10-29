"""Rhyme and syllable meter analyzer tool for Lyrics Sub-Agent."""
import re
from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field
from pypinyin import lazy_pinyin, Style

from src.models.common import QualityLineStat as LineStat, RhymeAnalysisResult


def analyze_rhyme_and_meter(lines: List[str]) -> RhymeAnalysisResult:
    """Analyze rhyme patterns and rhythmic meter for a list of lyric lines."""
    cleaned_lines = [line.strip() for line in lines if line.strip()]
    if not cleaned_lines:
        return RhymeAnalysisResult(line_stats=[], rhyme_scheme="Empty", average_syllables=0.0)

    line_stats: List[LineStat] = []
    rhyme_groups: Dict[str, List[int]] = {}
    total_chars = 0
    char_counts: List[int] = []

    for idx, line in enumerate(cleaned_lines, start=1):
        # Extract last Chinese character or word character
        m = re.findall(r"[\u4e00-\u9fa5a-zA-Z]", line)
        last_char = m[-1] if m else (line[-1] if line else "")
        vowel = None

        # Resolve actual Chinese finals or English phonetic rhymes
        if not vowel and last_char and "\u4e00" <= last_char <= "\u9fff":
            modal_particles = {"啊", "呀", "呢", "吧", "哦", "啦", "呐", "嘛", "哎"}
            target_char = last_char
            if last_char in modal_particles and len(m) > 1 and "\u4e00" <= m[-2] <= "\u9fff":
                target_char = m[-2]
            finals = lazy_pinyin(target_char, style=Style.FINALS, strict=False)
            vowel = finals[0] if finals and finals[0].isascii() and finals[0].isalpha() else None
        elif not vowel and last_char and ("a" <= last_char.lower() <= "z"):
            eng_match = re.findall(r"[a-zA-Z]+", line)
            if eng_match:
                word = eng_match[-1].lower()
                for suffix, fam in [("ight", "ai"), ("ite", "ai"), ("ay", "ei"), ("ey", "ei"),
                                   ("ee", "i"), ("ea", "i"), ("ow", "ou"), ("all", "ao"),
                                   ("aw", "ao"), ("ar", "a"), ("ing", "eng"), ("ong", "eng")]:
                    if word.endswith(suffix):
                        vowel = fam
                        break
                if not vowel and word.endswith("y"):
                    vowel = "ai"

        # Group finals by phonetic rhyme family, never by a character hash.
        families = {"iang":"ang","uang":"ang","ian":"an","uan":"an","van":"an",
                    "ing":"eng","ong":"eng","iong":"eng","iu":"ou","ui":"ei",
                    "uai":"ai","iao":"ao","uo":"o","e":"o"}
        vowel = families.get(vowel,vowel)

        char_cnt = len(m) if m else len(line)
        total_chars += char_cnt
        char_counts.append(char_cnt)

        if vowel:
            rhyme_groups.setdefault(vowel, []).append(idx)

        line_stats.append(
            LineStat(
                line_number=idx,
                text=line,
                char_count=char_cnt,
                last_char=last_char,
                rhyme_vowel=vowel,
            )
        )

    # Calculate average and variance
    avg_len = total_chars / len(cleaned_lines)
    variance = sum((c - avg_len) ** 2 for c in char_counts) / len(char_counts)
    regularity = max(0.0, 1.0 - (variance ** 0.5) / (avg_len + 1e-5))

    # Detect scheme (AABB, ABAB, AAAA)
    vowels_seq = [s.rhyme_vowel or "?" for s in line_stats]
    scheme = "Free"
    if len(vowels_seq) == 4:
        v1, v2, v3, v4 = vowels_seq
        if v1 == v2 and v3 == v4 and v1 != v3:
            scheme = "AABB"
        elif v1 == v3 and v2 == v4 and v1 != v2:
            scheme = "ABAB"
        elif v1 == v2 == v3 == v4:
            scheme = "AAAA"
        elif v2 == v4 and v1 != v3:
            scheme = "XAXA"

    feedback_notes = []
    if regularity < 0.6:
        feedback_notes.append("句长波动较大，建议均衡每句字数以契合乐句节拍。")
    if not any(len(g) >= 2 for g in rhyme_groups.values()):
        feedback_notes.append("句尾韵脚匹配较少，建议调整句尾词以增强押韵感。")
    else:
        feedback_notes.append(f"检测到韵律形态: {scheme}，韵脚覆盖良好。")

    return RhymeAnalysisResult(
        line_stats=line_stats,
        detected_rhymes=rhyme_groups,
        rhyme_scheme=scheme,
        average_syllables=round(avg_len, 2),
        meter_regularity=round(regularity, 2),
        feedback_notes=feedback_notes,
    )
