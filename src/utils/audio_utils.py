"""Full PCM integrity validation and explicit demo waveform synthesis."""
import os
import wave
import math
import struct
from pathlib import Path
from src.models.common import AudioInspectionResult
from src.utils.hash_utils import calculate_sha256


def inspect_and_validate_wav(file_path):
    result = AudioInspectionResult(is_valid=False)
    try:
        path = Path(file_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError("音频为空文件 (0 字节) 或不存在")
        result.file_size_bytes = path.stat().st_size
        result.sha256 = calculate_sha256(str(path))
        if result.file_size_bytes < 44:
            raise ValueError("音频文件过小，头部损坏")
        with open(path, "rb") as raw:
            header = raw.read(12)
            if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                raise ValueError("不是 RIFF/WAVE")
            declared_size = struct.unpack("<I", header[4:8])[0] + 8
            if declared_size > result.file_size_bytes:
                raise ValueError("RIFF 数据截断")
        with wave.open(str(path), "rb") as wf:
            result.sample_rate = wf.getframerate()
            result.channels = wf.getnchannels()
            width = wf.getsampwidth()
            result.bit_depth = width * 8
            frames = wf.getnframes()
            if result.sample_rate != 44100 or result.channels != 2 or width != 2:
                raise ValueError("交付音频必须为 44.1kHz / 16-bit / 双声道 PCM")
            if frames <= 0:
                raise ValueError("音频帧数必须大于 0")
            expected = frames * width * result.channels
            actual = 0
            while True:
                chunk = wf.readframes(65536)
                if not chunk:
                    break
                actual += len(chunk)
            if actual != expected:
                raise ValueError("音频数据截断，声明帧数与实际长度不一致")
            result.duration_seconds = frames / result.sample_rate
        result.is_valid = True
    except Exception as exc:
        result.error_message = str(exc)
    return result


def generate_synthetic_wav(
    file_path: str,
    duration_seconds: float = 15.0,
    sample_rate: int = 44100,
    channels: int = 2,
    base_freq_hz: float = 440.0,
    bpm: float = 120.0,
) -> AudioInspectionResult:
    """Generate a valid, playable PCM stereo WAV audio file with pleasant chord progression."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    
    # 4-chord progression cycle (I - V - vi - IV, classic pop progression)
    # 1 second per chord, 4 seconds per cycle
    chord_ratios = [
        (1.0, 1.25, 1.5),     # Root chord (I)
        (1.5, 1.875, 2.25),   # Dominant chord (V)
        (1.2, 1.44, 1.8),     # Submediant chord (vi)
        (1.333, 1.666, 2.0),  # Subdominant chord (IV)
    ]
    
    chord_seconds = 120.0 / bpm
    cycle_seconds = len(chord_ratios) * chord_seconds
    cycle_frames = int(sample_rate * cycle_seconds)
    cycle_buffer = bytearray()
    amplitude = 14000
    
    for i in range(cycle_frames):
        chord_idx = int(i / sample_rate / chord_seconds) % len(chord_ratios)
        r1, r2, r3 = chord_ratios[chord_idx]
        t = float(i) / sample_rate
        # Gentle pulse envelope
        beat_env = 0.85 + 0.15 * math.cos(2.0 * math.pi * (bpm / 60.0) * t)
        val = int(
            amplitude * beat_env * (
                0.45 * math.sin(2.0 * math.pi * base_freq_hz * r1 * t) +
                0.35 * math.sin(2.0 * math.pi * base_freq_hz * r2 * t) +
                0.20 * math.sin(2.0 * math.pi * base_freq_hz * r3 * t)
            )
        )
        val = max(-32768, min(32767, val))
        packed = struct.pack("<h", val)
        for _ in range(channels):
            cycle_buffer.extend(packed)

    total_frames = int(sample_rate * duration_seconds)
    bytes_per_frame = 2 * channels
    total_bytes = total_frames * bytes_per_frame
    cycle_bytes = len(cycle_buffer)
    
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        
        full_cycles = total_bytes // cycle_bytes
        remainder = total_bytes % cycle_bytes
        for _ in range(full_cycles):
            wf.writeframes(cycle_buffer)
        if remainder > 0:
            wf.writeframes(cycle_buffer[:remainder])

    return inspect_and_validate_wav(file_path)
