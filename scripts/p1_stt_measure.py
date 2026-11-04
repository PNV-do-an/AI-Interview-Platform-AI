"""Đo STT trước khi chốt: faster-whisper chạy CPU int8 trên máy 4GB VRAM.

    .venv/Scripts/python.exe scripts/p1_stt_measure.py [small|base|tiny]

In ra: thời gian tải model, độ dài âm thanh thực, hệ số RTF (processing / audio), và chữ kết luận.
"""
import asyncio
import io
import sys
import time
import wave

import imageio_ffmpeg
import numpy as np

VOICE = "vi-VN-HoaiMyNeural"
SENTENCES = [
    "Tôi tên là Minh, tôi có ba năm làm backend với Java và Spring Boot.",
    "Mình đã xây hệ thống phỏng vấn dùng WebRTC và có học thêm về React.",
    "Khi gặp vấn đề về hiệu năng, tôi đo truy vấn trước rồi mới thêm chỉ mục.",
]


def synth_mp3(text: str) -> bytes:
    import edge_tts

    buf = io.BytesIO()

    async def run():
        communicate = edge_tts.Communicate(text, VOICE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])

    asyncio.run(run())
    return buf.getvalue()


def mp3_to_pcm16k(mp3: bytes) -> tuple[np.ndarray, int]:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
            "-f", "wav", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "pipe:1"]
    out = subprocess_run(proc, mp3)
    with wave.open(io.BytesIO(out), "rb") as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0, 16000


def subprocess_run(cmd, stdin_bytes):
    import subprocess

    res = subprocess.run(cmd, input=stdin_bytes, capture_output=True)
    if res.returncode != 0:
        sys.exit("ffmpeg lỗi: " + res.stderr.decode(errors="ignore")[:400])
    return res.stdout


def main() -> None:
    size = sys.argv[1] if len(sys.argv) > 1 else "small"
    # Whisper tiếng Việt hay viết sai tên công nghệ; initial_prompt là cách sửa duy nhất
    # mà không phải đổi model (medium trên CPU máy này RTF ~2.4, không dùng được).
    prompt = None
    if "--prompt" in sys.argv:
        prompt = ("Đây là buổi phỏng vấn kỹ thuật phần mềm bằng tiếng Việt về Java, Spring Boot, "
                  "React, WebRTC, cơ sở dữ liệu, PostgreSQL, Docker, Kubernetes, backend, frontend, "
                  "API, REST, GraphQL, microservice, hiệu năng, chỉ mục, giao dịch.")

    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(size, device="cpu", compute_type="int8")
    print(f"model={size} tải hết {time.perf_counter() - t0:.1f}s  prompt={'có' if prompt else 'không'}")

    pcm, sr = mp3_to_pcm16k(synth_mp3(SENTENCES[0]))
    audio_s = len(pcm) / sr
    t0 = time.perf_counter()
    segments, info = model.transcribe(pcm, language="vi", vad_filter=True, initial_prompt=prompt)
    text = "".join(s.text for s in segments).strip()
    took = time.perf_counter() - t0
    print(f"audio={audio_s:.2f}s  xử_lý={took:.2f}s  RTF={took / audio_s:.2f}  lang={info.language}")
    print("nội dung:", text)

    # tiếng Việt dài hơn, đo tiếp độ ổn định + tỷ lệ từ khóa ngành giữ được
    keywords = ["backend", "spring", "react", "webrtc", "truy vấn", "chỉ mục", "phỏng vấn"]
    for s in SENTENCES:
        pcm, sr = mp3_to_pcm16k(synth_mp3(s))
        t0 = time.perf_counter()
        segments, _ = model.transcribe(pcm, language="vi", vad_filter=True, initial_prompt=prompt)
        got = "".join(x.text for x in segments).strip()
        took = time.perf_counter() - t0
        low = got.lower()
        hit = [k for k in keywords if k in low]
        print(f"audio={len(pcm) / sr:.2f}s took={took:.2f}s RTF={took / (len(pcm) / sr):.2f} "
              f"từ_khóa={len(hit)}{hit} -> {got}")


if __name__ == "__main__":
    main()
