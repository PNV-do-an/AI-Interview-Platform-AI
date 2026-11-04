"""Đo AI service end-to-end: gọi thật qua :8020 -> LiveTalking :8010 -> whisper -> rubric.

Dùng phiên avatar mà P0 để lại (lấy từ /api/admin/sessions) thay vì tự ký WebRTC: TTS và máy miệng
của LiveTalking chạy y như thật, chỉ thiếu trình duyệt nhận stream.

    .venv/Scripts/python.exe scripts/p1_ai_service_e2e.py
"""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AI = "http://127.0.0.1:8020"
LT = "http://127.0.0.1:8010"
JOB_TITLE = "Backend Java"
JD = ("Chúng tôi cần Backend Java. Yêu cầu: Spring Boot, PostgreSQL, Docker, Redis, Kafka. "
      "Ưu tiên ứng viên có kinh nghiệm React và CI/CD.")

timings: list[tuple[str, float]] = []


def step(name: str, fn):
    t0 = time.time()
    out = fn()
    dt = time.time() - t0
    timings.append((name, dt))
    print(f"{name:32s} {dt:6.2f}s")
    return out


def show(name: str, secs: float, note: str) -> None:
    timings.append((name, secs))
    print(f"{name:32s} {secs:6.2f}s  {note}")


def fail(msg: str) -> None:
    raise SystemExit("Đo thất bại: " + msg)


def expect_error(resp: requests.Response, status: int, needle: str) -> None:
    body = resp.text[:220]
    print(f"{'chan loi':32s} mong {status} `{needle}` -> {resp.status_code} {body}")
    if resp.status_code != status or needle not in body:
        fail(f"muon {status} `{needle}`, nhan {resp.status_code} {body[:160]}")


def make_vietnamese_wav(text: str) -> bytes:
    """EdgeTTS -> WAV 16k mono, coi như một clip thu âm từ trình duyệt."""
    import edge_tts
    import imageio_ffmpeg

    async def _mp3() -> bytes:
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, "vi-VN-HoaiMyNeural").stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    mp3 = asyncio.run(_mp3())
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                           "-f", "wav", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "pipe:1"],
                          input=mp3, capture_output=True)
    if proc.returncode != 0:
        fail("ffmpeg: " + proc.stderr.decode(errors="ignore")[:200])
    return proc.stdout


def open_avatar_session():
    """Mở phiên WebRTC thật qua /api/v1/ai/avatar/offer, giữ kết nối cho cả lần đo.

    Chạy aiortc trong event loop riêng ở một thread nền: phần đo vẫn là requests đồng bộ.
    Trả về (sessionid, ham_dong).
    """
    import asyncio
    import threading

    from aiortc import RTCPeerConnection, RTCSessionDescription

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    async def _open():
        pc = RTCPeerConnection()  # không STUN: hai tiến trình trên cùng máy
        pc.addTransceiver("audio", direction="recvonly")
        pc.addTransceiver("video", direction="recvonly")
        await pc.setLocalDescription(await pc.createOffer())
        r = requests.post(AI + "/api/v1/ai/avatar/offer",
                          json={"sdp": pc.localDescription.sdp,
                                "type": pc.localDescription.type}, timeout=60)
        if r.status_code != 200:
            fail(f"/avatar/offer -> {r.status_code} {r.text[:200]}")
        answer = r.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["answerSdp"],
                                                            type=answer["answerType"]))
        return pc, answer["avatarSessionId"]

    pc, avatar_sid = asyncio.run_coroutine_threadsafe(_open(), loop).result(timeout=90)

    def _close():
        asyncio.run_coroutine_threadsafe(pc.close(), loop).result(timeout=30)
        loop.call_later(1, loop.stop)

    return avatar_sid, _close


def main() -> None:
    health = step("GET /health", lambda: requests.get(AI + "/health", timeout=10).json())
    print("  ", json.dumps(health, ensure_ascii=False))
    avatar_sid, close_avatar = step("POST /avatar/offer (WebRTC that)", open_avatar_session)
    print("   avatar session:", avatar_sid)

    sess = step("POST /session", lambda: requests.post(
        AI + "/api/v1/ai/session",
        json={"jobTitle": JOB_TITLE, "jdText": JD, "avatarSessionId": avatar_sid},
        timeout=10).json())
    sid = sess["sessionid"]
    print("   ai session:", sid)

    q0 = step("GET question 0 (avatar nói)", lambda: requests.get(
        AI + f"/api/v1/ai/session/{sid}/question", params={"speak": "true"}, timeout=60).json())
    print("   câu hỏi 0:", q0["questionText"][:110])

    # /human trả code 0 trước khi có âm thanh, nên con số FE cần là "mất bao lâu avatar cất tiếng".
    t0 = time.time()
    spoke_after = None
    while time.time() - t0 < 20:
        if requests.get(AI + f"/api/v1/ai/session/{sid}/speaking", timeout=10).json().get("speaking"):
            spoke_after = time.time() - t0
            break
        time.sleep(0.4)
    show("avatar cất tiếng sau", spoke_after if spoke_after else 20.0,
         "im lặng — FE phải đọc phụ đề" if spoke_after is None else "đã nói")

    q0_again = step("GET question 0 lần hai", lambda: requests.get(
        AI + f"/api/v1/ai/session/{sid}/question", params={"speak": "false"}, timeout=30).json())
    if q0_again["questionText"] != q0["questionText"]:
        fail("hỏi lại đổi câu — FE retry sẽ thành hai lượt")
    print("   câu hỏi giữ nguyên khi retry: OK")

    a0 = step("POST answer 0 (gõ chữ)", lambda: requests.post(
        AI + f"/api/v1/ai/session/{sid}/answer",
        json={"answerText": "Em làm Java được bốn năm, chủ yếu Spring Boot với PostgreSQL, gần nhất "
                             "em viết dịch vụ thanh toán phục vụ 2 triệu lượt gọi mỗi ngày.",
              "durationSec": 42}, timeout=60).json())
    print("   lượt 0 chốt, lượt kế:", (a0.get("next") or {}).get("questionText", "")[:110])

    wav = make_vietnamese_wav(
        "Em dùng Redis để cache bảng giá, nhờ đó thời gian phản hồi giảm từ 300 xuống 40 mili giây.")
    a1 = step(f"POST answer 1 (âm thanh {len(wav)} bytes, lượt lạnh)", lambda: requests.post(
        AI + f"/api/v1/ai/session/{sid}/answer/audio",
        files={"file": ("answer.wav", wav, "audio/wav")},
        data={"questionIndex": 1, "durationSec": 6}, timeout=180))
    print("   chữ hóa được:", a1.json().get("answerText"))
    if "redis" not in a1.json().get("answerText", "").lower():
        print("   CANH BAO: STT khong ra tu khoa Redis")

    wav2 = make_vietnamese_wav("Em triển khai CI/CD bằng GitHub Actions, mỗi lần merge là chạy 400 unit test.")
    a2 = step(f"POST answer 2 (âm thanh {len(wav2)} bytes, lượt nóng)", lambda: requests.post(
        AI + f"/api/v1/ai/session/{sid}/answer/audio",
        files={"file": ("answer2.wav", wav2, "audio/wav")},
        data={"questionIndex": 2, "durationSec": 6}, timeout=180))
    print("   chữ hóa được:", a2.json().get("answerText"))

    expect_error(requests.post(AI + f"/api/v1/ai/session/{sid}/answer",
                               json={"answerText": "abc", "questionIndex": 9}, timeout=30),
                 400, "chưa tới")
    expect_error(requests.post(AI + f"/api/v1/ai/session/{sid}/answer",
                               json={"answerText": "abc", "questionIndex": 0}, timeout=30),
                 400, "đã được chốt")
    expect_error(requests.post(AI + f"/api/v1/ai/session/{sid}/answer/audio",
                               files={"file": ("x.txt", b"khong phai audio", "text/plain")},
                               timeout=30), 400, "âm thanh")

    tr = step("GET /transcript", lambda: requests.get(
        AI + f"/api/v1/ai/session/{sid}/transcript", timeout=10).json())
    print("   số lượt trong transcript:", len(tr["transcript"]))

    ev = step("POST /evaluate", lambda: requests.post(
        AI + f"/api/v1/ai/session/{sid}/evaluate", timeout=60).json())
    print("   rubric:", json.dumps(ev["rubric"], ensure_ascii=False), "version:", ev["rubricVersion"])
    needed = {"chuyenMon", "duAn", "tuDuy", "truyenDat", "mucKhop"}
    if set(ev["rubric"]) != needed or not all(isinstance(v, int) and 0 <= v <= 100
                                              for v in ev["rubric"].values()):
        fail("rubric không khớp hợp đồng BE spec 012")
    if len(ev["strengths"]) > 4000 or len(ev["improvements"]) > 4000:
        fail("strengths/improvements vượt trần 4000 của BE")

    step("DELETE /session", lambda: requests.delete(AI + f"/api/v1/ai/session/{sid}", timeout=10).status_code)
    expect_error(requests.get(AI + f"/api/v1/ai/session/{sid}/transcript", timeout=10),
                 404, "không tồn tại")

    # Phiên P0 để lại hôm trước vẫn render ngốn CPU — kiểm tra đóng WebRTC có thật sự giải phóng.
    close_avatar()
    time.sleep(3)
    left = requests.get(LT + "/api/admin/sessions", timeout=10).json()["data"]["sessions"]
    print("   phiên avatar còn lại sau khi đóng WebRTC:", len(left))

    print("\n=== thời gian từng bước ===")
    for name, dt in timings:
        print(f"{name:32s} {dt:6.2f}s")


if __name__ == "__main__":
    main()
