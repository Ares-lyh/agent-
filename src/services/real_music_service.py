"""Compatibility adapter using the same strict music gateway as the AudioAgent."""
from src.tools.music_api_tool import RealMusicEngineClient
from src.models.composition import Composition, AudioMetadata
from src.models.common import GenerationParameters
from src.tools.acoustic_qc_tool import inspect_acoustic_quality
from src.services.vocal_direction import resolve_vocals

class RealMusicServiceAdapter:
    def __init__(self, provider=None, api_key=None, base_url=None, timeout=30,
                 enable_fallback=False, session=None):
        self.client = RealMusicEngineClient(provider,api_key,base_url,timeout,session=session)
        self.provider = self.client.provider

    def generate(self, project_id, brief, lyrics, output_audio_path, version="v1", feedback=None):
        vocals = resolve_vocals(brief, feedback)
        result = self.client.submit_and_wait("\n".join(filter(None, (vocals.instruction(), lyrics.to_markdown(), feedback))),
            brief.genre,brief.mood,120,"C Major",brief.duration_seconds,output_audio_path,
            lyrics="\n\n".join("["+section.section_type+"]\n"+"\n".join(section.lines)
                                 for section in lyrics.sections),
            vocal_language=brief.lyrics_language)
        qc = inspect_acoustic_quality(output_audio_path)
        if not qc.is_valid:
            from src.core.exceptions import AudioCorruptedError
            raise AudioCorruptedError(qc.error_message)
        return Composition(project_id=project_id,composition_version=version,bpm=120,key="C Major",
            genre=brief.genre,mood=brief.mood,arrangement_notes="由配置音乐网关生成",
            vocal_requirements=vocals,
            music_model_params=GenerationParameters(provider=result.provider,model=self.client.model,is_mock=self.client.is_mock,
                                                     task_id=result.task_id,feedback=feedback),
            audio_metadata=AudioMetadata(file_path=output_audio_path,sha256=qc.sha256,
                sample_rate=qc.sample_rate,channels=qc.channels,bit_depth=qc.bit_depth,
                duration_seconds=qc.duration_seconds,file_size_bytes=qc.file_size_bytes),
            handoff_notes="等待人工试听")
