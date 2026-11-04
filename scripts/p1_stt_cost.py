"""Tách riêng chi phí STT: decode ffmpeg + whisper, đo từng lần trong cùng một tiến trình.

Dùng để phân biệt 25 giây/câu đo qua HTTP là do whisper, do ffmpeg, hay do CPU bị LiveTalking chiếm.

    .venv/Scripts/python.exe scripts/p1_stt_cost.py
"""
from __future__ import annotations

import gc
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, ".")

from app.audio import decode_any, rms, seconds_of, wav_to_float32  # noqa: E402
from app.config import Settings  # noqa: E402
from app.stt import Transcriber  # noqa: E402

from scripts.p1_ai_service_e2e import make_vietnamese_wav  # noqa: E402

TEXT = ("Em dùng Redis để cache bảng giá, nhờ đó thời gian phản hồi giảm từ 300 xuống 40 mili giây.")


def main() -> None:
    settings = Settings.from_env()
    t0 = time.time()
    mp3_wav = make_vietnamese_wav(TEXT)
    print(f"edge tts tạo file âm thanh: {time.time()-t0:.2f}s  wav={len(mp3_wav)} bytes "
          f"({seconds_of(mp3_wav):.1f}s noi)")

    t0 = time.time()
    pcm = decode_any(mp3_wav)
    samples, rate = wav_to_float32(pcm)
    print(f"ffmpeg decode: {time.time()-t0:.2f}s  rms={rms(samples):.4f} rate={rate}")

    stt = Transcriber(settings.stt_model, settings.stt_device, settings.stt_compute)
    t0 = time.time()
    stt.warmup()
    print(f"load model: {time.time()-t0:.2f}s")

    for i in range(3):
        t0 = time.time()
        text, dur = stt.transcribe(samples)
        print(f"lần {i+1}: {time.time()-t0:.2f}s cho {dur:.1f}s nói -> {text}")

    # So sánh mô hình nhỏ hơn trên cùng máy đang chạy avatar — để đổi tốc độ lấy độ chính xác có số.
    # Phải giải phóng bản đang load trước: hai model Whisper cùng sống trong RAM 8GB là
    # mkl_malloc fail (đo 26/10).
    del stt
    gc.collect()
    for size in ("base", "tiny"):
        stt2 = Transcriber(size, "cpu", "int8")
        t0 = time.time()
        stt2.warmup()
        load = time.time() - t0
        t0 = time.time()
        text2, dur2 = stt2.transcribe(samples)
        t = time.time() - t0
        print(f"{size}: load {load:.1f}s, transcribe {t:.2f}s cho {dur2:.1f}s nói -> {text2}")
        del stt2
        gc.collect()


if __name__ == "__main__":
    main()
