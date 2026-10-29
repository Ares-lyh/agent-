"""Native ACEMusic completions and configurable asynchronous music gateway.

Gateway contract: POST /generate -> {task_id} or {audio_url};
GET /tasks/{id} -> {status,audio_url}. The acemusic provider uses its own adapter.
Production configuration errors and remote failures never become demo success.
"""
import os
import time
import subprocess
import shutil
from pathlib import Path
from urllib.parse import urlparse, quote
import requests
from src.config import settings
from src.core.exceptions import RateLimitExceededError, ModelTimeoutError, AudioCorruptedError
from src.models.music import MusicGenerationRequest
from src.models.workflow import MusicTaskResponse, MusicTaskResult
from src.utils.audio_utils import generate_synthetic_wav, inspect_and_validate_wav
from src.utils.persistence import atomic_write

class RealMusicEngineClient:
    def __init__(self, provider=None, api_key=None, base_url=None, timeout=30,
                 max_poll_seconds=300, session=None):
        self.provider = (provider or settings.MUSIC_PROVIDER).lower()
        self.api_key = api_key if api_key is not None else (
            settings.SUNO_API_KEY if self.provider == "suno" else
            settings.MINIMAX_API_KEY if self.provider == "minimax" else settings.REAL_MUSIC_API_KEY)
        self.base_url = base_url if base_url is not None else (
            settings.REAL_MUSIC_BASE_URL or (settings.SUNO_BASE_URL if self.provider == "suno" else ""))
        self.timeout = timeout
        self.max_poll_seconds = max_poll_seconds
        self.session = session or requests.Session()
        self.is_mock = self.provider == "mock"
        self.model = settings.ACEMUSIC_MODEL if self.provider == "acemusic" else None

    def _request(self, method, url, **kwargs):
        last = None
        for attempt in range(3):
            try:
                response = getattr(self.session, method)(url, timeout=self.timeout, **kwargs)
                if response.status_code == 429:
                    raise RateLimitExceededError("音乐网关 429 频控")
                if response.status_code >= 500:
                    raise ModelTimeoutError(f"音乐网关 HTTP {response.status_code}")
                if response.status_code not in (200,201,202):
                    raise AudioCorruptedError(f"音乐网关 HTTP {response.status_code}")
                return response
            except (requests.Timeout, requests.ConnectionError, RateLimitExceededError, ModelTimeoutError) as exc:
                last = exc
                if attempt < 2:
                    time.sleep(.2 * 2 ** attempt)
        if isinstance(last, (RateLimitExceededError, ModelTimeoutError)):
            raise last
        raise ModelTimeoutError("音乐网关网络请求超时") from last

    def validate_configuration(self):
        if self.is_mock:
            return
        if self.provider == "unconfigured" or not self.api_key or not self.base_url:
            raise ValueError("未配置真实音乐服务。GPT 文本模型可规划和作词，但不能生成歌曲音频；请配置 MUSIC_PROVIDER、REAL_MUSIC_BASE_URL、REAL_MUSIC_API_KEY。演示需显式 MUSIC_PROVIDER=mock")
        if urlparse(self.base_url).scheme not in ("http","https"):
            raise ValueError("音乐网关地址必须是 HTTP(S)")

    def submit_and_wait(self, prompt, genre, mood, bpm, key, duration_seconds,
                        output_wav_path, task_id=None, on_task=None, idempotency_key=None,
                        lyrics=None, vocal_language="zh"):
        destination = Path(output_wav_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self.is_mock:
            generate_synthetic_wav(str(destination), duration_seconds=duration_seconds,
                                   base_freq_hz=220 + bpm)
            return MusicTaskResult(provider="mock", task_id="demo-local", audio_path=str(destination))
        self.validate_configuration()
        if self.provider == "acemusic":
            from src.tools.acemusic_api import generate
            return generate(self, prompt, genre, mood, bpm, key, duration_seconds,
                output_wav_path, lyrics, vocal_language, task_id, on_task, idempotency_key)
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if not task_id:
            payload = MusicGenerationRequest(prompt=prompt, tags=f"{genre}, {mood}, {key}, {bpm}bpm",
                         title=f"Song in {key}", duration=duration_seconds)
            response = self._request("post", self.base_url.rstrip("/") + "/generate",
                                     json=payload.model_dump(), headers=headers)
            if response.content.startswith(b"RIFF") or "audio" in response.headers.get("content-type",""):
                self._convert(response.content, destination)
                return MusicTaskResult(provider=self.provider,task_id="direct",audio_path=str(destination))
            data = MusicTaskResponse.model_validate(response.json())
            data = data.data or data
            task_id = data.task_id or data.id
            if task_id and on_task:
                on_task(task_id)  # Persist before polling or downloading.
            audio_url = data.audio_url or data.download_url
            if audio_url:
                self._download_audio(audio_url, destination)
                return MusicTaskResult(provider=self.provider,task_id=task_id or "direct-url",audio_path=str(destination))
            if not task_id:
                raise AudioCorruptedError("音乐网关缺少 task_id/audio_url")
        return self._poll_task_until_done(task_id, destination, headers)

    def _poll_task_until_done(self, task_id, destination, headers):
        deadline = time.monotonic() + self.max_poll_seconds
        interval = .25
        while time.monotonic() < deadline:
            response = self._request("get", self.base_url.rstrip("/") + "/tasks/" + quote(task_id,safe=""),
                                     headers=headers)
            data = MusicTaskResponse.model_validate(response.json())
            data = data.data or data
            if (data.status or "").lower() in ("completed","success","done"):
                url = data.audio_url or data.download_url
                if not url:
                    raise AudioCorruptedError("音乐任务成功但没有音频链接")
                self._download_audio(url, destination)
                return MusicTaskResult(provider=self.provider, task_id=task_id, audio_path=str(destination))
            if (data.status or "").lower() in ("failed","error"):
                raise AudioCorruptedError("远端音乐任务失败")
            time.sleep(min(interval, max(0, deadline-time.monotonic())))
            interval = min(interval*1.5,5)
        raise ModelTimeoutError(f"音乐任务 {task_id} 轮询超时，可 resume 继续原任务")

    def _download_audio(self, url, destination):
        if urlparse(url).scheme not in ("http", "https"):
            raise AudioCorruptedError("无效的音频下载地址")
        response = self._request("get", url, stream=True)
        source = Path(str(destination) + ".download")
        total_size = 0
        try:
            with open(source, "wb") as stream_out:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        total_size += len(chunk)
                        if total_size > 512 * 1024 * 1024:
                            raise AudioCorruptedError("音频超过 512 MB")
                        stream_out.write(chunk)
            self._convert_from_path(source, destination)
        finally:
            source.unlink(missing_ok=True)

    def _convert(self, content, destination):
        source = Path(str(destination) + ".download")
        atomic_write(source, content)
        try:
            self._convert_from_path(source, destination)
        finally:
            source.unlink(missing_ok=True)

    def _convert_from_path(self, source, destination):
        destination = Path(destination)
        converted = Path(str(destination) + ".converted.wav")
        try:
            check = inspect_and_validate_wav(str(source))
            if check.is_valid:
                atomic_write(destination, source.read_bytes())
            else:
                try:
                    executable = settings.FFMPEG_PATH
                    if executable == "ffmpeg" and not shutil.which(executable):
                        import imageio_ffmpeg
                        executable = imageio_ffmpeg.get_ffmpeg_exe()
                    subprocess.run([executable, "-v", "error", "-y", "-i", str(source),
                         "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(converted)],
                         check=True, timeout=120, capture_output=True,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                except (OSError, ImportError, RuntimeError, subprocess.SubprocessError) as exc:
                    raise AudioCorruptedError("音频不是合规 WAV，转码失败；请配置 FFMPEG_PATH") from exc
                if not inspect_and_validate_wav(str(converted)).is_valid:
                    raise AudioCorruptedError("转码后音频损坏")
                atomic_write(destination, converted.read_bytes())
        finally:
            converted.unlink(missing_ok=True)
