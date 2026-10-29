"""Native ACEMusic music completions; never treat it as a generic task API."""
import base64
import binascii
from pathlib import Path
import requests
from src.models.acemusic import AudioConfig, ChatMessage, MusicRequest, MusicResponse
from src.models.workflow import MusicTaskResult
from src.core.exceptions import AudioCorruptedError, ModelTimeoutError, RateLimitExceededError
from src.utils.persistence import atomic_write


def vocal_language_code(language):
    aliases = {"中文": "zh", "汉语": "zh", "chinese": "zh", "英文": "en", "英语": "en",
               "english": "en", "日语": "ja", "japanese": "ja", "韩语": "ko", "korean": "ko"}
    code = aliases.get(language.strip().lower(), language.strip().lower())
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ValueError("请将歌词语言设置为支持的名称或双字母语言代码")
    return code


def generate(client, prompt, genre, mood, bpm, key, duration_seconds, output_path,
             lyrics, vocal_language, task_id=None, on_task=None, operation_id=None):
    if not lyrics or not lyrics.strip():
        raise ValueError("ACEMusic 必须接收已批准的纯歌词，禁止自动另写歌词")
    endpoint = client.base_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    cache = Path(str(output_path) + ".acemusic-response.json")
    if cache.exists():
        response = MusicResponse.model_validate_json(cache.read_text(encoding="utf-8"))
    else:
        if task_id:
            # The hosted synchronous API documents no result lookup/idempotency guarantee.
            raise ModelTimeoutError("ACEMusic 上一次同步请求结果未确认；为避免重复生成，已暂停自动重发。请核对服务端记录后处理该任务。")
        payload = MusicRequest(model=client.model,
            messages=[ChatMessage(role="user", content=f"{genre}; {mood}; {prompt}")],
            lyrics=lyrics, audio_config=AudioConfig(duration=duration_seconds, bpm=bpm,
                key_scale=key, vocal_language=vocal_language_code(vocal_language)))
        marker = "acemusic:pending:" + (operation_id or Path(output_path).name)
        if on_task:
            on_task(marker)  # Commit the intent before the synchronous network call.
        try:
            result = client.session.post(endpoint + "/chat/completions",
                json=payload.model_dump(),
                headers={"Authorization": "Bearer " + client.api_key, "Content-Type": "application/json"},
                timeout=(10, client.max_poll_seconds), allow_redirects=False)
        except requests.RequestException:
            raise ModelTimeoutError("ACEMusic 同步请求未收到确定结果；任务已保留，请勿重复提交") from None
        if result.status_code in (400, 401, 403, 404, 405, 422, 429):
            if on_task:
                on_task(None)  # Explicit rejection: no accepted generation to recover.
            if result.status_code == 429:
                raise RateLimitExceededError("ACEMusic 触发频控，请稍后 resume")
            raise AudioCorruptedError(f"ACEMusic 请求被拒绝 (HTTP {result.status_code})")
        if result.status_code != 200:
            raise ModelTimeoutError(f"ACEMusic 返回 HTTP {result.status_code}，生成结果尚未确认")
        try:
            response = MusicResponse.model_validate(result.json())
        except (ValueError, TypeError):
            raise AudioCorruptedError("ACEMusic 未返回有效的音乐音频响应") from None
        atomic_write(cache, response.model_dump_json())
    if response.model != client.model:
        raise AudioCorruptedError("ACEMusic 返回模型与配置不一致")
    if on_task:
        on_task(response.id)
    url = response.choices[0].message.audio[0].audio_url.url
    if url.startswith("data:"):
        try:
            metadata, encoded = url.split(",", 1)
            if not metadata.startswith("data:audio/") or not metadata.endswith(";base64"):
                raise ValueError("invalid audio data URL")
            if len(encoded) > 715827884:
                raise ValueError("audio payload too large")
            content = base64.b64decode(encoded, validate=True)
            if not content:
                raise ValueError("empty audio")
        except (ValueError, binascii.Error):
            raise AudioCorruptedError("ACEMusic 音频 Base64 无效或为空") from None
        client._convert(content, Path(output_path))
    else:
        client._download_audio(url, Path(output_path))
    return MusicTaskResult(provider="acemusic", task_id=response.id, audio_path=str(output_path))
