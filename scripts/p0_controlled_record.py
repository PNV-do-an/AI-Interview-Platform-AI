"""Ghi một clip kiểm soát có trình tự IM LẶNG -> NÓI -> IM LẶNG, kèm mốc thời gian.

Mục đích: tạo dữ liệu đo sạch cho scripts/p0_lipsync_measure.py. Với template tĩnh,
khung hình lúc im lặp lại đúng ảnh gốc, nên mọi chuyển động ở vùng miệng đều là
khẩu hình do model tạo ra — không còn nhiễu trôi nền làm lệch phép đo.

Dùng: python scripts/p0_controlled_record.py --id vn_static_test --text "..." [--idle 3]
"""
import argparse
import asyncio
import json
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LT = os.path.join(ROOT, "vendored", "LiveTalking")
SERVER = "http://localhost:8010"
DEFAULT_TEXT = "Xin chào, tôi là người phỏng vấn AI của HireMind. Rất vui được gặp bạn hôm nay."

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


async def run(session_id: str, text: str, idle: float, gap_s: float, out_json: str):
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    got = {"video": 0}

    @pc.on("track")
    async def on_track(track):
        if track.kind != "video":
            return

        async def pump():
            while pc.connectionState not in ("closed", "failed", "disconnected"):
                try:
                    await asyncio.wait_for(track.recv(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
                got["video"] += 1
        asyncio.ensure_future(pump())

    pc.addTransceiver("audio", direction="recvonly")
    pc.addTransceiver("video", direction="recvonly")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    r = requests.post(f"{SERVER}/offer",
                      json={"sdp": pc.localDescription.sdp, "type": "offer", "sessionid": session_id},
                      timeout=30)
    r.raise_for_status()
    answer = r.json()
    if "sessionid" not in answer:
        sys.exit(f"/offer thất bại: {answer}")
    # server tự sinh UUID cho phiên, không dùng id ta gửi -> phải lấy lại từ response
    session_id = answer["sessionid"]
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    print(f"[webrtc] server gán sessionid={session_id}")

    while pc.connectionState != "connected" and got["video"] == 0:
        await asyncio.sleep(0.2)
    print(f"[webrtc] state={pc.connectionState}, đã nhận {got['video']} frame")

    def post(route, payload):
        resp = requests.post(f"{SERVER}{route}", json=payload, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        if body.get("code", 0) != 0:  # lỗi nghiệp vụ vẫn trả HTTP 200
            sys.exit(f"{route} lỗi: {body}")
        return body

    events = {}

    post("/record", {"type": "start_record", "sessionid": session_id})
    events["record_start"] = time.perf_counter()
    print(f"[record] bắt đầu, chờ {idle:.1f}s im lặng")
    await asyncio.sleep(idle)

    events["speech_request"] = time.perf_counter()
    post("/human", {"text": text, "type": "echo", "sessionid": session_id})
    print(f"[human] đã gửi câu: {text}")

    speaking, t_last = False, None
    # is_speaking rơi giữa các câu (dấu chấm) -> chỉ coi là dứt khi im liên tục >= gap_s
    deadline, gap_start = time.perf_counter() + 120, None
    while time.perf_counter() < deadline:
        st = post("/is_speaking", {"sessionid": session_id}).get("data")
        if st:
            gap_start = None
            if not speaking:
                speaking = True
                events["speaking_start"] = time.perf_counter()
                print(f"[speaking] bắt đầu nói sau "
                      f"{events['speaking_start'] - events['speech_request']:.2f}s")
            t_last = time.perf_counter()
        elif speaking:
            if gap_start is None:
                gap_start = time.perf_counter()
            elif time.perf_counter() - gap_start >= gap_s:
                events["speaking_end"] = t_last
                print(f"[speaking] dứt câu, {t_last - events['speaking_start']:.2f}s "
                      f"âm thanh (ngừng sau {gap_s:.1f}s liên tục im lặng)")
                break
        await asyncio.sleep(0.1)
    else:
        print("[speaking] CẢNH BÁO: quá 120s không xác định được điểm dứt câu")
    if "speaking_start" not in events:
        sys.exit("/is_speaking không bao giờ True — kiểm tra log server (TTS có lỗi không?)")
    events.setdefault("speaking_end", t_last or time.perf_counter())

    await asyncio.sleep(idle)
    events["idle_end"] = time.perf_counter()
    post("/record", {"type": "end_record", "sessionid": session_id})
    print(f"[record] đã dừng, chờ ffmpeg mux")
    await asyncio.sleep(3.0)

    rec = os.path.join(LT, "data", "record", f"{session_id}.mp4")
    t0 = events["record_start"]
    payload = {
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sessionid": session_id,
        "file": rec,
        "fps": 25,
        "clip_seconds": (events["idle_end"] - t0),
        "speech_window_frames": [int((events["speaking_start"] - t0) * 25),
                                 int((events["speaking_end"] - t0) * 25)],
        "idle_pre_frames": [0, int((events["speech_request"] - t0) * 25)],
        "idle_post_frames": [int((events["speaking_end"] - t0) * 25) + 25,
                             int((events["idle_end"] - t0) * 25)],
        "text": text,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if os.path.isfile(rec):
        print(f"OK: {rec} ({os.path.getsize(rec)} bytes), "
              f"cửa sổ nói = frame {payload['speech_window_frames']}")
    else:
        print(f"CẢNH BÁO: không thấy file ghi {rec}")
    await pc.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="vn_static_test", help="sessionid, cũng là tên file record")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--idle", type=float, default=3.0, help="số giây im lặng trước và sau câu nói")
    ap.add_argument("--gap", type=float, default=1.5,
                    help="số giây im liên tục được coi là đã dứt câu (mặc định 1.5)")
    ap.add_argument("--events", default="", help="file JSON mốc thời gian (mặc định docs/events_<id>.json)")
    args = ap.parse_args()
    out = args.events or os.path.join(ROOT, "docs", f"events_{args.id}.json")
    asyncio.run(run(args.id, args.text, args.idle, args.gap, out))


if __name__ == "__main__":
    main()
