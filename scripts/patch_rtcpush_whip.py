"""Sửa rtcpush của LiveTalking để đẩy WHIP vào MediaMTX (idempotent, chạy trên Colab).

 Vendor code gửi SDP bằng `session.post(push_url, data=sdp)` mà không đặt Content-Type;
aiohttp bèn gửi `text/plain; charset=utf-8`, và MediaMTX trả về 400 "invalid Content-Type"
(đã đo 31/10 bằng whip_probe). WHIP yêu cầu `application/sdp`. Ngoài header, patch thêm
kiểm tra HTTP status: trước đó lỗi đẩy stream bị ẩn và biểu hiện thành treo ở
setRemoteDescription. Patch thứ hai ép ưu tiên H264 cho track video của handle_rtcpush: MediaMTX
không đưa VP8 vào HLS nên nếu để VP8 thì luồng avatar chỉ có tiếng, không có hình.
"""
from __future__ import annotations

import os
import sys

LT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "vendored", "LiveTalking")
TARGET = os.path.join(LT, "server", "rtc_manager.py")

OLD = """        async with aiohttp.ClientSession() as session:
            async with session.post(push_url, data=pc.localDescription.sdp) as response:
                answer_sdp = await response.text()
"""

NEW = '''        async with aiohttp.ClientSession() as session:
            # PATCH-LOCAL (MediaMTX WHIP): aiohttp mặc định gửi text/plain nên bị 400
            # "invalid Content-Type"; WHIP yêu cầu application/sdp.
            sdp_headers = {"Content-Type": "application/sdp"}
            async with session.post(push_url, data=pc.localDescription.sdp,
                                    headers=sdp_headers) as response:
                if response.status >= 300:
                    raise RuntimeError(
                        f"WHIP push thất bại (HTTP {response.status}): {await response.text()}")
                answer_sdp = await response.text()
'''

# Đường /offer ép ưu tiên H264 (rtc_manager._create_pc_and_answer), còn handle_rtcpush thì không,
# nên aiortc chào VP8 trước. MediaMTX chỉ mux H264 sang HLS, VP8 bị "skipping track" -> mất hình.
ANCHOR = """        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        await pc.setLocalDescription(await pc.createOffer())
"""

H264 = '''        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        # PATCH-LOCAL (HLS chỉ nhận H264): ưu tiên H264 như _create_pc_and_answer, VP8 giữ làm dự phòng.
        caps = RTCRtpSender.getCapabilities("video")
        prefs = list(filter(lambda x: x.name == "H264", caps.codecs))
        prefs += list(filter(lambda x: x.name == "VP8", caps.codecs))
        prefs += list(filter(lambda x: x.name == "rtx", caps.codecs))
        pc.getTransceivers()[1].setCodecPreferences(prefs)

        await pc.setLocalDescription(await pc.createOffer())
'''


def main() -> int:
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()
    block = src.split("async def handle_rtcpush", 1)[-1].split("async def shutdown", 1)[0]
    applied = []
    if "application/sdp" not in block:
        if OLD not in block:
            sys.exit(f"Không thấy khối rtcpush gốc trong {TARGET} — vendor đã đổi, sửa tay.")
        src = src.replace(OLD, NEW, 1)
        applied.append("Content-Type: application/sdp")
    if "setCodecPreferences" not in block:
        if ANCHOR not in block:
            sys.exit(f"Không thấy chỗ chèn ưu tiên codec trong {TARGET} — vendor đã đổi, sửa tay.")
        src = src.replace(ANCHOR, H264, 1)
        applied.append("uu tien codec H264")
    if not applied:
        print("[patch] rtc_manager.py đã vá xong (Content-Type + H264) — bỏ qua")
        return 0
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src)
    print("[patch] " + TARGET + ": " + ", ".join(applied))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
