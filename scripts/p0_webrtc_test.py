"""Client P0 headless: mở phiên WebRTC với LiveTalking qua /offer,
đưa giọng tiếng Việt (EdgeTTS) vào /humanaudio, ghi record mp4,
đo frame thực nhận + GPU trong lúc nói."""
import asyncio
import json
import subprocess
import sys
import tempfile
import threading
import time

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVER = "http://localhost:8010"
TEXT = "Xin chào, tôi là người phỏng vấn AI của HireMind. Rất vui được gặp bạn hôm nay."
VOICE = "vi-VN-NamMinhNeural"

stop_sampling = threading.Event()
gpu_samples = []


def gpu_sampler():
    while not stop_sampling.is_set():
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True).stdout.strip()
        if out:
            util, mem = [int(x) for x in out.split(",")]
            gpu_samples.append((util, mem))
        time.sleep(1)


async def synth_vietnamese(text: str) -> str:
    import edge_tts
    mp3p = tempfile.mktemp(suffix=".mp3")
    wavp = mp3p.replace(".mp3", ".wav")
    await edge_tts.Communicate(text, VOICE).save(mp3p)
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                    "-i", mp3p, "-ar", "16000", "-ac", "1", wavp], check=True)
    return wavp


async def run():
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))  # host-only, không phụ thuộc STUN ngoài
    stats = {"video_frames": 0, "audio_frames": 0, "first_t": None, "last_t": None}

    @pc.on("track")
    async def on_track(track):
        print(f"[webrtc] nhận track: {track.kind}")
        kind = track.kind

        async def pump():
            while pc.connectionState not in ("closed", "failed", "disconnected"):
                try:
                    await asyncio.wait_for(track.recv(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    print(f"[recv] {kind} kết thúc: {type(e).__name__}")
                    break
                t = time.perf_counter()
                if stats["first_t"] is None:
                    stats["first_t"] = t
                    print(f"[stream] frame {kind} đầu tiên tại +{t - T0:.2f}s")
                stats["last_t"] = t
                stats[f"{kind}_frames"] += 1
                if stats[f"{kind}_frames"] % 50 == 0:
                    print(f"  {kind} frames: {stats[f'{kind}_frames']}")
        asyncio.ensure_future(pump())

    pc.addTransceiver("audio", direction="recvonly")
    pc.addTransceiver("video", direction="recvonly")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    r = requests.post(f"{SERVER}/offer", json={"sdp": pc.localDescription.sdp,
                                               "type": pc.localDescription.type}, timeout=30)
    r.raise_for_status()
    answer = r.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    sessionid = answer["sessionid"]
    print(f"[webrtc] phiên: {sessionid}")
    global T0
    T0 = time.perf_counter()

    # /record cô lập riêng (nghi chặn event loop aiohttp khi ffmpeg pipe đầy)
    # requests.post(f"{SERVER}/record", json={"type": "start_record", "sessionid": sessionid}, timeout=10)

    wavpath = await synth_vietnamese(TEXT)
    t0 = time.perf_counter()
    with open(wavpath, "rb") as f:
        r = requests.post(f"{SERVER}/humanaudio",
                          files={"file": ("p0.wav", f, "audio/wav")},
                          data={"sessionid": sessionid}, timeout=30)
    print(f"[api] /humanaudio -> {r.status_code} (+{time.perf_counter()-t0:.2f}s gửi)")

    th = threading.Thread(target=gpu_sampler, daemon=True)
    th.start()

    # poll trạng thái nói tối đa 40s
    speaking_seen = False
    for _ in range(80):
        await asyncio.sleep(0.5)
        try:
            s = requests.post(f"{SERVER}/is_speaking", json={"sessionid": sessionid}, timeout=5).json()
            if s.get("data"):
                speaking_seen = True
        except Exception:
            pass
        if speaking_seen and not s.get("data"):
            break
    print(f"[state] is_speaking từng = {speaking_seen}")

    # requests.post(f"{SERVER}/record", json={"type": "end_record", "sessionid": sessionid}, timeout=10)
    await asyncio.sleep(1)
    stop_sampling.set()
    th.join(timeout=3)

    dur = (stats["last_t"] - stats["first_t"]) if stats["first_t"] else 0
    result = {
        "sessionid": sessionid,
        "video_frames": stats["video_frames"],
        "audio_frames": stats["audio_frames"],
        "stream_seconds": round(dur, 2),
        "client_fps": round(stats["video_frames"] / dur, 1) if dur else 0,
        "gpu_util_avg_pct": round(sum(g for g, _ in gpu_samples) / len(gpu_samples), 1) if gpu_samples else None,
        "gpu_mem_peak_mib": max((m for _, m in gpu_samples), default=None),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # tải bản ghi để kiểm chứng khẩu hình offline (tắt khi cô lập lỗi record)
    await pc.close()
    # await asyncio.sleep(2)
    # r = requests.get(f"{SERVER}/record/{sessionid}", timeout=30)
    # if r.status_code == 200:
    #     out = tempfile.gettempdir() + f"/p0_{sessionid[:8]}.mp4"
    #     with open(out, "wb") as f:
    #         f.write(r.content)
    #     print(f"[record] saved -> {out} ({len(r.content)//1024} KB)")
    # else:
    #     print(f"[record] HTTP {r.status_code} — không có file ghi")


if __name__ == "__main__":
    T0 = 0
    asyncio.run(run())
