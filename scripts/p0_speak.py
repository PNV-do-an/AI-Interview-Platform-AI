"""Đo P0: sinh giọng tiếng Việt bằng EdgeTTS, đưa vào LiveTalking qua /humanaudio.

Chạy SAU khi app.py đã khởi động:
    .venv/Scripts/python.exe scripts/p0_speak.py "Câu cần avatar nói"
"""
import asyncio
import io
import json
import subprocess
import sys
import time
import wave

import requests

SERVER = "http://localhost:8010"
SESSIONID = ""  # rỗng = phiên gần nhất do web/index.html tạo; điền sessionid nếu cô lập nhiều phiên
VOICE = "vi-VN-NamMinhNeural"  # đổi thành vi-VN-ThanhHaNeural / nữ nếu muốn

async def synth(text: str) -> bytes:
    import edge_tts
    buf = io.BytesIO()
    communicate = edge_tts.Communicate(text, VOICE)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()

def mp3_to_wav_16k(mp3: bytes) -> bytes:
    import soundfile  # noqa: F401 (đảm bảo đã cài)
    import tempfile, os
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3)
        mp3path = f.name
    wavpath = mp3path.replace(".mp3", ".wav")
    subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", mp3path,
         "-ar", "16000", "-ac", "1", wavpath],
        check=True,
    )
    data = open(wavpath, "rb").read()
    os.unlink(mp3path); os.unlink(wavpath)
    return data

def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "Xin chào, tôi là trợ lý phỏng vấn AI của HireMind."
    t0 = time.perf_counter()
    mp3 = asyncio.run(synth(text))
    print(f"TTS EdgeTTS: {len(mp3)} bytes mp3, {time.perf_counter()-t0:.2f}s")

    try:
        wav = mp3_to_wav_16k(mp3)
        with wave.open(io.BytesIO(wav)) as w:
            dur = w.getnframes() / w.getframerate()
        print(f"ffmpeg: wav 16k mono, {dur:.1f}s")
    except Exception as e:
        print(f"ffmpeg lỗi ({e}) → fallback /human để server tự EdgeTTS")
        r = requests.post(f"{SERVER}/human",
                          json={"text": text, "type": "echo", "sessionid": SESSIONID})
        print(r.status_code, r.text)
        return

    t1 = time.perf_counter()
    files = {"file": ("p0.wav", wav, "audio/wav"), "sessionid": (None, SESSIONID)}
    r = requests.post(f"{SERVER}/humanaudio", files=files)
    print(f"POST /humanaudio → {r.status_code} {r.text} ({time.perf_counter()-t1:.2f}s)")
    print(f"Avatar đang nói — mở http://localhost:8010/index.html, bấm Start Connection")
    print(f"(giữ nguyên sessionid mặc định của trang), rồi log server sẽ hiện inferfps/finalfps.")

if __name__ == "__main__":
    main()
