"""Full-track acoustic checks using the shared validated audio contract."""
import wave
from array import array
from src.models.common import AudioInspectionResult
from src.utils.audio_utils import inspect_and_validate_wav

AcousticInspectionResult = AudioInspectionResult


def inspect_acoustic_quality(wav_path):
    result = inspect_and_validate_wav(wav_path)
    if not result.is_valid:
        return result
    total = clipped = silent = 0
    with wave.open(wav_path, "rb") as wf:
        while True:
            raw = wf.readframes(65536)
            if not raw:
                break
            samples = array("h")
            samples.frombytes(raw)
            import sys
            if sys.byteorder != "little":
                samples.byteswap()
            total += len(samples)
            clipped += sum(abs(s) >= 32760 for s in samples)
            silent += sum(abs(s) < 20 for s in samples)
    result.clipping_ratio = clipped / total
    result.silence_ratio = silent / total
    if result.clipping_ratio > .005 or result.silence_ratio > .98:
        result.is_valid = False
        result.error_message = f"声学不合格：削顶率 {result.clipping_ratio:.3%}，静音率 {result.silence_ratio:.3%}"
    return result
