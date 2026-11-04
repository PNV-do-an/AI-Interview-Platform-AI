"""Sửa rtcpush của LiveTalking để đẩy WHIP vào MediaMTX (idempotent, chạy trên Colab).

 Vendor code gửi SDP bằng `session.post(push_url, data=sdp)` mà không đặt Content-Type;
aiohttp bèn gửi `text/plain; charset=utf-8`, và MediaMTX trả về 400 "invalid Content-Type"
(đã đo 31/10 bằng whip_probe). WHIP yêu cầu `application/sdp`. Ngoài header, patch thêm
kiểm tra HTTP status: trước đó lỗi đẩy stream bị ẩn và biểu hiện thành treo ở
setRemoteDescription.
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


def main() -> int:
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()
    block = src.split("async def handle_rtcpush", 1)[-1].split("async def shutdown", 1)[0]
    if "application/sdp" in block:
        print("[patch] rtc_manager.py đã có Content-Type: application/sdp — bỏ qua")
        return 0
    if OLD not in block:
        sys.exit(f"Không thấy khối rtcpush gốc trong {TARGET} — vendor đã đổi, sửa tay.")
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(src.replace(OLD, NEW, 1))
    print(f"[patch] {TARGET}: WHIP push nay gui Content-Type: application/sdp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
