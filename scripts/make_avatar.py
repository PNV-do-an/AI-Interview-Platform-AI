"""Tạo avatar pack cho LiveTalking từ một ảnh tĩnh hoặc video quay bằng điện thoại.

Dùng:
  # ảnh tĩnh -> video có drift nhẹ
  python scripts/make_avatar.py --src assets/a.png --id my_avatar

  # video quay: cắt 40s từ giây 5, về 576x768@25, kiểm tra nhận diện mặt trước khi build
  python scripts/make_avatar.py --src "D:/Downloads/IMG_0042.mp4" --id vn_gesturing --start 5 --seconds 40

Video gốc không bị sửa; bản chuẩn hoá ghi ra assets/<id>.mp4.
Tắt server LiveTalking trước khi chạy (phát hiện mặt chiếm GPU).
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LT = os.path.join(ROOT, "vendored", "LiveTalking")
ASSETS = os.path.join(ROOT, "assets")
W, H, FPS_DEFAULT = 576, 768, 25

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ffmpeg_exe():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def warn_gpu_busy():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        used = int(out.splitlines()[0])
    except Exception:
        return
    if used > 2500:
        print(f"CẢNH BÁO: GPU đang tốn {used} MiB — nhiều khi là server LiveTalking."
              " Hãy tắt trước khi build avatar (s3fd cần VRAM).")


def image_to_video(src, out, seconds, fps, still):
    if still:
        vf = f"scale={W}:{H}"
    else:
        vf = (
            f"scale={2*W}:{2*H},"
            "zoompan=z='1.03+0.012*sin(on/55*PI)':"
            "x='iw/2-(iw/zoom/2)+10*sin(on/41*PI)':"
            "y='ih/2-(ih/zoom/2)+7*sin(on/31*PI)+3*cos(on/67*PI)':"
            f"d=1:s={W}x{H}:fps={fps}"
        )
    subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", src, "-vf", vf, "-t", str(seconds), "-r", str(fps),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
    return out


def normalize_video(src, out, start, seconds, fps, fit):
    """Chuẩn hoá video quay thô: đúng kích thước, đúng fps, cắt khoảng cần dùng."""
    if fit == "crop":
        vf = (f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},setsar=1")
    else:  # pad: giữ nguyên khung hình, đệm hai bên bằng nền đen
        vf = f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", src, "-t", str(seconds), "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-an", out]
    subprocess.run(cmd, check=True)
    return out


def probe(path):
    import cv2

    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or FPS_DEFAULT
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames = []
    step = max(1, int(n / 24))
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0 and len(frames) < 24:
            frames.append(f)
        i += 1
    cap.release()
    return {"frames": n, "fps": fps, "w": w, "h": h, "seconds": n / fps}, frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="ảnh (.png/.jpg) hoặc video quay (.mp4/.mov/.mkv)")
    ap.add_argument("--id", required=True, help="avatar_id, sẽ thành data/avatars/<id>")
    ap.add_argument("--start", type=float, default=0.0, help="giây bắt đầu cắt (video quay)")
    ap.add_argument("--seconds", type=float, default=14.0, help="độ dài template dùng thật")
    ap.add_argument("--fps", type=int, default=FPS_DEFAULT, help="LiveTalking luôn chạy 25fps")
    ap.add_argument("--fit", choices=["crop", "pad"], default="crop",
                    help="crop = lấp đầy khung 3:4 (phổ biến nhất khi quay dọc); pad = giữ khung, đệm đen")
    ap.add_argument("--still", action="store_true", help="chỉ cho ảnh: template tĩnh tuyệt đối (đo kiểm soát)")
    ap.add_argument("--img-size", type=int, default=256, help="kích thước face crop, 256 cho wav2lip256")
    ap.add_argument("--pads", nargs="+", type=int, default=[0, 10, 0, 0],
                    help="[top bottom left right] cộng thêm vào box khuôn mặt")
    ap.add_argument("--batch", type=int, default=8, help="batch phát hiện mặt; giảm nếu OOM")
    ap.add_argument("--no-check", action="store_true", help="bỏ bước kiểm tra nhận diện mặt mẫu")
    args = ap.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isfile(src):
        sys.exit(f"Không tìm thấy nguồn: {src}")
    os.makedirs(ASSETS, exist_ok=True)
    is_image = os.path.splitext(src)[1].lower() in (".png", ".jpg", ".jpeg")

    sys.path.insert(0, LT)
    os.chdir(LT)

    if is_image:
        video = os.path.join(ASSETS, f"{args.id}.mp4")
        print(f"Đổi ảnh tĩnh -> video: {video} ({'tĩnh' if args.still else 'có drift nhẹ'})")
        image_to_video(src, video, args.seconds, args.fps, args.still)
    else:
        warn_gpu_busy()
        video = os.path.join(ASSETS, f"{args.id}.mp4")
        print(f"Chuẩn hoá video quay -> {video} "
              f"({W}x{H}@{args.fps}, cắt {args.seconds}s từ giây {args.start}, fit={args.fit})")
        normalize_video(src, video, args.start, args.seconds, args.fps, args.fit)

    meta, samples = probe(video)
    print(f"  video: {meta['frames']} frame, {meta['seconds']:.1f}s, {meta['w']}x{meta['h']}, {meta['fps']:.0f}fps")

    if not args.no_check:
        import numpy as np
        from avatars.wav2lip import face_detection  # noqa: F401  (bảo đảm module import được)
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        det = face_detection.FaceAlignment(face_detection.LandmarksType._2D, flip_input=False, device=device)
        boxes = []
        for i in range(0, len(samples), args.batch):
            chunk = np.asarray(samples[i:i + args.batch])
            try:
                boxes.extend(det.get_detections_for_batch(chunk))
            except RuntimeError:
                print(f"  OOM với batch={args.batch} -> thử --batch {max(1, args.batch // 2)}")
                raise SystemExit(3)
        del det
        got = [b for b in boxes if b is not None]
        rate = len(got) / max(1, len(boxes))
        print(f"  phát hiện mặt ở {len(got)}/{len(boxes)} frame mẫu ({rate*100:.0f}%) trên {device}")
        if rate < 0.9:
            sys.exit("KHÔNG ĐẠT: dưới 90% frame mẫu nhận được mặt. Kiểm tra ánh sáng/góc quay/"
                     " mặt bị che, hoặc chạy lại với --start khác.")
        c = np.asarray([[ (b[0]+b[2])/2, (b[1]+b[3])/2] for b in got])
        spread = (c.max(axis=0) - c.min(axis=0))
        print(f"  độ lệch tâm khuôn mặt lớn nhất giữa các mẫu: {spread[0]:.0f}px ngang, {spread[1]:.0f}px dọc")
        if spread.max() > W * 0.18:
            print("  CẢNH BÁO: mặt di chuyển nhiều > 18% chiều ngang khung. wav2lip chỉ vẽ lại vùng"
                  " miệng trong box cố định theo frame, lệch lớn làm méo/loá miệng.")

    from avatars.wav2lip.genavatar import generate_avatar

    print(f"Tạo avatar pack '{args.id}' từ {video} (img_size={args.img_size}, pads={args.pads})")
    generate_avatar(
        video_path=video,
        avatar_id=args.id,
        save_path=os.path.join(LT, "data", "avatars"),
        img_size=args.img_size,
        pads=args.pads,
        nosmooth=args.still,
        face_det_batch_size=args.batch,
    )
    out = os.path.join(LT, "data", "avatars", args.id)
    n = len(os.listdir(os.path.join(out, "face_imgs")))
    print(f"OK: {n} frame -> {out}")
    print(f"Chạy thử: scripts/run_server.py --config <abs path> ... rồi thêm avatar_id: {args.id}")


if __name__ == "__main__":
    main()
