"""Mock Music Generation Model with real WAV synthesis and fault injection."""
import os
import time
from typing import Optional, Dict, Any
from src.models.brief import Brief
from src.models.lyrics import Lyrics
from src.models.composition import Composition, AudioMetadata
from src.utils.audio_utils import generate_synthetic_wav, inspect_and_validate_wav
from src.core.exceptions import RateLimitExceededError, ModelTimeoutError, AudioCorruptedError
from src.config import settings


class MockMusicModel:
    """Mock music generation engine capable of synthesizing valid PCM audio
    and injecting network faults (429 rate limit, timeouts, empty files).
    """

    def __init__(
        self,
        simulate_429_count: int = 0,
        simulate_empty_file: bool = False,
        simulate_timeout: bool = False,
        simulate_corrupt_file: bool = False,
        delay_seconds: float = 0.05,
    ):
        self.simulate_429_count = simulate_429_count
        self.current_429_attempts = 0
        self.simulate_empty_file = simulate_empty_file
        self.simulate_timeout = simulate_timeout
        self.simulate_corrupt_file = simulate_corrupt_file
        self.delay_seconds = delay_seconds

    def _infer_musical_parameters(self, genre: str, mood: str) -> tuple[int, str, float]:
        """Infer suitable BPM, Key, and audio pitch based on genre and mood."""
        genre_lower = genre.lower()
        if "摇滚" in genre or "rock" in genre_lower:
            return 138, "G Major", 392.0
        elif "电子" in genre or "electronic" in genre_lower:
            return 128, "D Minor", 293.66
        elif "lo-fi" in genre_lower or "流行" in genre:
            return 85, "Eb Major", 311.13
        elif "国风" in genre:
            return 96, "A Minor (羽调式)", 440.0
        return 120, "C Major", 261.63

    def generate(
        self,
        project_id: str,
        brief: Brief,
        lyrics: Lyrics,
        output_audio_path: str,
        version: str = "v1",
        feedback: Optional[str] = None,
    ) -> Composition:
        """Execute composition and audio generation."""
        # 1. Fault Injection: Timeout
        if self.simulate_timeout:
            raise ModelTimeoutError(f"音乐生成模型调用超时 (超过预算阈值)")

        # 2. Fault Injection: 429 Rate Limit
        if self.current_429_attempts < self.simulate_429_count:
            self.current_429_attempts += 1
            raise RateLimitExceededError(
                f"音乐生成模型触发 429 频控 (第 {self.current_429_attempts}/{self.simulate_429_count} 次)"
            )

        # Simulate execution latency
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)

        os.makedirs(os.path.dirname(os.path.abspath(output_audio_path)), exist_ok=True)

        # 3. Fault Injection: Empty File (0 bytes)
        if self.simulate_empty_file:
            with open(output_audio_path, "wb") as f:
                pass  # create 0 bytes file
            inspection = inspect_and_validate_wav(output_audio_path)
            raise AudioCorruptedError(inspection.error_message or "生成音频为空文件 (0 字节)")

        # 4. Fault Injection: Corrupt Header (< 44 bytes)
        if self.simulate_corrupt_file:
            with open(output_audio_path, "wb") as f:
                f.write(b"RIFF....WAVEcorrupt")
            inspection = inspect_and_validate_wav(output_audio_path)
            raise AudioCorruptedError(inspection.error_message or "生成音频头部损坏")

        # 5. Normal Sound Synthesis
        bpm, musical_key, pitch = self._infer_musical_parameters(brief.genre, brief.mood)
        
        # Determine actual audio duration (controlled via settings.MOCK_AUDIO_SAMPLE_DURATION, default 15s)
        target_sample_duration = settings.MOCK_AUDIO_SAMPLE_DURATION
        if target_sample_duration > 0:
            sample_audio_duration = min(float(brief.duration_seconds), target_sample_duration)
        else:
            sample_audio_duration = float(brief.duration_seconds)
        
        if feedback:
            import hashlib
            pitch *= 1 + (int(hashlib.sha256(feedback.encode()).hexdigest()[:4], 16) % 17 + 1) / 100
            if "减半" in feedback or "halve" in feedback.lower():
                bpm = max(31, bpm // 2)
        inspection = generate_synthetic_wav(
            file_path=output_audio_path,
            duration_seconds=sample_audio_duration,
            sample_rate=44100,
            channels=2,
            base_freq_hz=pitch,
            bpm=bpm,
        )

        if not inspection.is_valid:
            raise AudioCorruptedError(f"生成的音频未能通过校验: {inspection.error_message}")

        # Build detailed section arrangement
        section_arrangements = []
        for sec in lyrics.sections:
            section_arrangements.append({
                "section_name": sec.section_name,
                "emotion": sec.emotion_tag,
                "instrumentation": f"主奏乐器结合 {brief.genre} 风格，情绪对齐 {sec.emotion_tag}",
                "dynamic_level": "Fortissimo" if "副歌" in sec.section_name or "Chorus" in sec.section_type else "Mezzo-Piano",
            })

        audio_metadata = AudioMetadata(
            format="wav",
            sample_rate=inspection.sample_rate,
            channels=inspection.channels,
            bit_depth=inspection.bit_depth,
            duration_seconds=inspection.duration_seconds,
            file_size_bytes=inspection.file_size_bytes,
            file_path=output_audio_path,
            sha256=inspection.sha256,
        )

        composition = Composition(
            project_id=project_id,
            composition_version=version,
            bpm=bpm,
            key=musical_key,
            genre=brief.genre,
            mood=brief.mood,
            arrangement_notes=(
                f"依据 brief 风格 [{brief.genre}] 与情绪 [{brief.mood}] 完成编曲规划；"
                f"采用 {musical_key} 调性，速度定为 {bpm} BPM，全面契合目标受众。"
            ),
            section_arrangements=section_arrangements,
            music_model_params={
                "model_engine": "mock-music-synthesizer-v1",
                "provider": "mock",
                "is_mock": True,
                "feedback": feedback,
                "sample_rate": inspection.sample_rate,
                "channels": inspection.channels,
                "bit_depth": inspection.bit_depth,
                "allow_sampling": brief.allow_sampling,
            },
            audio_metadata=audio_metadata,
            handoff_notes=(
                f"产物包括高品质立体声 WAV 音频文件 ({output_audio_path})，"
                f"文件大小 {inspection.file_size_bytes} 字节，SHA-256 为 {inspection.sha256}。"
                f"已就绪供人工审核与物料包打包。"
            ),
        )

        return composition
