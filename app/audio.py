"""Âm thanh vào từ trình duyệt: đổi webm/ogg/mp4 mà MediaRecorder xuất ra thành WAV 16k mono.

Không bắt FE phải chuyển định dạng trước khi gửi; ffmpeg đọc mọi thứ trình duyệt đưa.
Giọng nói của avatar do tiến trình LiveTalking tự tổng hợp, không đi qua file này.
"""
from __future__ import annotations

import io
import subprocess
import wave

import imageio_ffmpeg
import numpy as np

SAMPLE_RATE = 16000


def decode_any(container_bytes: bytes) -> bytes:
    """Bất kỳ âm thanh nào trình duyệt gửi (webm/ogg/mp4/m4a/wav) -> WAV 16k mono."""
    if not container_bytes:
        raise ValueError("Âm thanh trống")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "wav", "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", "pipe:1"],
        input=container_bytes, capture_output=True,
    )
    if proc.returncode != 0:
        raise ValueError("Không đọc được âm thanh: " + proc.stderr.decode(errors="ignore")[:200])
    return proc.stdout


def wav_to_float32(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("cần WAV 16-bit mono")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0, w.getframerate()


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def seconds_of(wav_bytes: bytes) -> float:
    """Số giây thật của WAV. ffmpeg ghi ra pipe không quay lại sửa header được nên nframes khai
    2^31-1; con số đúng phải tính từ độ dài byte PCM, header chỉ dùng để lấy sample rate."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        frames = w.getnframes()
    pcm_bytes = len(wav_bytes) - 44
    real = pcm_bytes / float(rate * width * channels)
    return min(frames / float(rate), real) if pcm_bytes > 0 else frames / float(rate)
