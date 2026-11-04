"""P0 launcher cho LiveTalking.

Vendored code không sửa; chỉ monkeypatch tại runtime:
aiortc>=1.16 (DIRECTIONS index-based and_direction) raise ValueError
"khi SDP answer không có a=direction — đường /offer của LiveTalking +
client aiortc đầu cuối đều rơi vào đây. None == sendrecv theo RFC 8829.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vendored", "LiveTalking")


def patch_aiortc():
    import aiortc.rtcpeerconnection as rpc
    from aiortc import sdp

    DIRECTIONS = sdp.DIRECTIONS
    orig = rpc.and_direction

    def and_direction(a, b):
        if a is None:
            a = "sendrecv"
        if b is None:
            b = "sendrecv"
        return DIRECTIONS[DIRECTIONS.index(a) & DIRECTIONS.index(b)]

    rpc.and_direction = and_direction
    print("[patch] aiortc.and_direction -> None-safe (sendrecv)")


def main():
    # /record của LiveTalking gọi subprocess "ffmpeg" — tên file ảnh hưởng:
    # imageio-ffmpeg phân phối ffmpeg-win-x86_64-v7.1.exe, cần symlink ffmpeg.exe
    import imageio_ffmpeg
    src = imageio_ffmpeg.get_ffmpeg_exe()
    bindir = os.path.dirname(src)
    link = os.path.join(bindir, "ffmpeg.exe")
    if not os.path.exists(link):
        try:
            os.symlink(src, link)
        except OSError:  # Windows không có quyền symlink → copy
            import shutil
            shutil.copy2(src, link)
    os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]
    os.chdir(LT_DIR)
    sys.path.insert(0, LT_DIR)
    patch_aiortc()
    from app import main as lt_main
    lt_main()


if __name__ == "__main__":
    main()
