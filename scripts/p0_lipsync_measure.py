"""Đo mức độ đồng bộ khẩu hình / âm thanh trong một video do LiveTalking ghi lại.

Ba tín hiệu được tính trên cùng trục thời gian:
  A. motion  = |crop frame i - crop frame i-1| ở vùng môi
  B. dev     = |crop frame i - crop khung HÌNH GỐC (template)| ở vùng môi
               -> đây là phần model thực sự vẽ lại; nếu avatar chỉ lặp ảnh tĩnh thì dev = 0
  C. audio   = RMS biên độ âm thanh lấy mẫu theo khung hình

Dải hàng được chọn là môi được tự xác định từ hồ sơ chuyển động theo hàng (không phải
hằng số đoán trước). Sau đó tương quan Pearson(A hoặc B, C) với trễ -6..+6 frame.

Nếu có file mốc từ scripts/p0_controlled_record.py, in thêm so sánh trực tiếp
giữa cửa sổ NÓI và hai cửa sổ IM LẶNG.

Dùng: python scripts/p0_lipsync_measure.py <video.mp4> <avatar_id> [events.json]
"""
import argparse
import json
import os
import pickle
import subprocess
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LT = os.path.join(ROOT, "vendored", "LiveTalking")
FPS = 25.0
SR = 16000
ALIGN_ROWS = (90, 230)      # dải dòng dùng để căn khung: nền + trán/mắt (không có môi)
GRID = (128, 128)           # lưới chuẩn khi đưa crop khuôn mặt về cùng kích thước

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ffmpeg_exe():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def read_frames(path, max_frames=3000):
    cap = cv2.VideoCapture(path)
    frames = []
    while len(frames) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    return frames


def audio_envelope(path, n_frames):
    """RMS biên độ âm thanh, lấy mẫu theo từng khung hình video."""
    fd, raw = tempfile.mkstemp(suffix=".raw")
    os.close(fd)
    try:
        subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", path,
             "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", raw],
            check=True,
        )
        pcm = np.fromfile(raw, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        os.remove(raw)
    spf = int(round(SR / FPS))
    usable = (len(pcm) // spf) * spf
    env = np.sqrt(np.mean(pcm[:usable].reshape(-1, spf) ** 2, axis=1)) if usable else np.array([])
    if len(env) < n_frames:
        env = np.pad(env, (0, n_frames - len(env)))
    return env[:n_frames], len(pcm) / SR


def norm(img):
    img = img.astype(np.float32)
    return (img - img.mean()) / (img.std() + 1e-6)


def crop_gray(frame, box):
    by1, by2, bx1, bx2 = box
    h, w = frame.shape[:2]
    y1, y2 = max(0, int(by1)), min(h, int(by2))
    x1, x2 = max(0, int(bx1)), min(w, int(bx2))
    g = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, GRID, interpolation=cv2.INTER_AREA)


def load_avatar(avatar_id):
    d = os.path.join(LT, "data", "avatars", avatar_id)
    pkl, imgs = os.path.join(d, "coords.pkl"), os.path.join(d, "full_imgs")
    if not (os.path.isfile(pkl) and os.path.isdir(imgs)):
        return None, None, None
    with open(pkl, "rb") as f:
        boxes = np.asarray(pickle.load(f), dtype=np.float32)
    align, faces = [], []
    for name in sorted(os.listdir(imgs)):
        img = cv2.imread(os.path.join(imgs, name))
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        align.append(cv2.resize(g[ALIGN_ROWS[0]:ALIGN_ROWS[1], :], (96, 48),
                                interpolation=cv2.INTER_AREA).astype(np.float32))
    for i, name in enumerate(sorted(os.listdir(imgs))):
        img = cv2.imread(os.path.join(imgs, name))
        if img is None:
            continue
        faces.append(crop_gray(img, boxes[i]))
    return boxes, (np.stack(align) if align else None), (np.stack(faces) if faces else None)


def estimate_offset(frames, tmpls):
    """Tìm chỉ số khung template ứng với frame 0 của video ghi."""
    if tmpls is None or not len(frames):
        return 0, 0, 0
    n = len(frames)
    idxs = list(range(min(8, n))) + list(range(max(0, n - 8), n))
    votes = []
    for i in idxs:
        g = cv2.cvtColor(frames[i], cv2.COLOR_BGR2GRAY)[ALIGN_ROWS[0]:ALIGN_ROWS[1], :]
        q = cv2.resize(g, (96, 48), interpolation=cv2.INTER_AREA).astype(np.float32)
        d = np.abs(tmpls - q[None, :, :]).mean(axis=(1, 2))
        votes.append((int(np.argmin(d)) - i) % len(tmpls))
    off, cnt = np.unique(np.asarray(votes), return_counts=True)
    return int(off[np.argmax(cnt)]), int(cnt.max()), len(idxs)


def find_band(prof, frac=0.20):
    """Dải hàng liên tiếp có tổng lớn nhất -> vị trí môi trên lưới khuôn mặt."""
    H = len(prof)
    k = max(3, int(H * frac))
    csum = np.concatenate([[0.0], np.cumsum(prof)])
    starts = np.arange(0, H - k + 1)
    scores = csum[starts + k] - csum[starts]
    best = int(starts[np.argmax(scores)])
    avg = csum[-1] / H * k
    return best, best + k, float(scores.max() / avg if avg > 0 else 1.0)


def detrend(x, win):
    if len(x) <= win:
        return x - x.mean()
    kernel = np.ones(win) / win
    slow = np.convolve(x, kernel, mode="same")
    slow[: win // 2] = x[: win // 2].mean()
    slow[-win // 2:] = x[-win // 2:].mean()
    return x - slow


def pearson(a, b):
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def shift(x, k):
    if k == 0:
        return x
    out = np.zeros_like(x)
    if k > 0:
        out[k:] = x[:-k]
    else:
        out[:k] = x[-k:]
    return out


def corr_report(name, sig, audio, skip=30):
    best = (-2.0, 0)
    parts = []
    for k in range(-6, 7):
        r = pearson(detrend(sig, 25)[skip:], detrend(shift(audio, k), 25)[skip:])
        parts.append(f"{k:+d}:{r:.2f}")
        if r > best[0]:
            best = (r, k)
    print(f"  {name} ~ audio: " + " ".join(parts))
    print(f"    >>> r={best[0]:.3f} tại trễ {best[1]:+d} frame ({best[1]/FPS*1000:+.0f} ms)")
    return best


def window_stats(name, sig, ev):
    print(f"  {name}: " + " | ".join(
        f"{lab} frame[{a}:{b}]={sig[a:min(b, len(sig))].mean():.4f}"
        for lab, (a, b) in ev.items() if b > a)
    )


def montage(frames, boxes, offset, r0, r1, idx_hi, idx_lo, audio, path, dev=None):
    """Ghép crop vùng môi của các frame máy nhất / ít máy nhất kèm giá trị âm thanh."""
    def panel(indices):
        tiles = []
        for i in indices:
            by1, by2, bx1, bx2 = boxes[(i + offset) % len(boxes)]
            fh = by2 - by1
            my1 = int(by1 + fh * r0 / GRID[1])
            my2 = int(by1 + fh * r1 / GRID[1])
            tile = frames[i][my1:my2, int(bx1):int(bx2)].copy()
            tile = cv2.resize(tile, (160, 70))
            if tile.ndim == 2:
                tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
            txt = f"f{i} a={audio[i]:.3f}" + (f" d={dev[i]:.3f}" if dev is not None else "")
            cv2.putText(tile, txt, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
            cv2.putText(tile, txt, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
            tiles.append(tile)
        while len(tiles) < 8:
            tiles.append(np.zeros((70, 160, 3), np.uint8))
        return np.vstack([np.hstack(tiles[r * 4:(r + 1) * 4]) for r in range(2)])

    hi, lo = panel(idx_hi), panel(idx_lo)
    img = np.vstack([hi, np.full((16, hi.shape[1], 3), 255, np.uint8), lo])
    for text, y in (("PHAN 1: 8 frame co khau hinh manh nhat", 13),
                    ("PHAN 2: 8 frame it khau hinh nhat (im lang)", hi.shape[0] + 29)):
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
    cv2.imwrite(path, img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("avatar")
    ap.add_argument("events", nargs="?", default="", help="docs/events_<id>.json nếu là clip kiểm soát")
    args = ap.parse_args()

    frames = read_frames(args.video)
    n = len(frames)
    audio, a_seconds = audio_envelope(args.video, n)
    boxes, tmpls, tmpl_faces = load_avatar(args.avatar)
    if boxes is None:
        sys.exit(f"Không tìm thấy pack avatar {args.avatar}")
    offset, votes, ballot = estimate_offset(frames, tmpls)

    print(f"{os.path.basename(args.video)}  (avatar={args.avatar})")
    print(f"  {n} frame video ({n/FPS:.2f}s), audio {a_seconds:.2f}s | "
          f"pack có {len(tmpl_faces)} frame, offset căn = {offset} (khớp {votes}/{ballot})")

    crops = np.stack([norm(crop_gray(f, boxes[(i + offset) % len(boxes)])) for i, f in enumerate(frames)])
    ref = tmpl_faces[(np.arange(n) + offset) % len(tmpl_faces)]
    ref = np.stack([norm(r) for r in ref])

    dev_face = np.abs(crops - ref).mean(axis=(1, 2))
    mot = np.concatenate([[0.0], np.abs(np.diff(crops, axis=0)).mean(axis=(1, 2))])

    prof_dev = np.abs(crops - ref).mean(axis=(0, 2))
    prof_mot = np.abs(np.diff(crops, axis=0)).mean(axis=(0, 2))
    prof = prof_dev if dev_face.max() > mot.max() * 0.5 else prof_mot
    which = "deviation-vs-template" if prof is prof_dev else "motion"
    r0, r1, conc = find_band(prof)
    print(f"  dải môi tự hiệu chỉnh từ hồ sơ {which}: hàng [{r0},{r1}]/{GRID[1]} "
          f"(đậm đặc {conc:.2f}x trung bình)")
    print("  profile deviation theo hàng (mỗi 8 hàng): " +
          " ".join(f"{prof_dev[i]:.3f}" for i in range(0, GRID[1], 8)))

    band = slice(r0, r1)
    diff_band = crops[:, band, :] - ref[:, band, :]
    dev = np.abs(diff_band).mean(axis=(1, 2))
    motb = np.concatenate([[0.0], np.abs(np.diff(crops[:, band, :], axis=0)).mean(axis=(1, 2))])

    print(f"  motion(miệng)  mean={motb.mean():.4f} p50={np.median(motb):.4f} p95={np.percentile(motb,95):.4f} max={motb.max():.4f}")
    print(f"  dev vs ảnh gốc mean={dev.mean():.4f} p50={np.median(dev):.4f} p95={np.percentile(dev,95):.4f} max={dev.max():.4f}")

    rb = corr_report("motion", motb, audio)
    rd = corr_report("dev    ", dev, audio)

    # cửa sổ suy từ chính âm thanh trong file (đất khách quan hơn mốc wall-clock,
    # vì /is_speaking có thể rơi giữa các câu)
    say_a = audio > 0.35 * audio.max()
    quiet_a = audio < 0.08 * audio.max()
    if say_a.sum() >= 5 and quiet_a.sum() >= 5:
        print(f"  theo năng lượng âm thanh: NÓI {int(say_a.sum())} frame "
              f"dev={dev[say_a].mean():.4f} motion={motb[say_a].mean():.4f} | "
              f"IM {int(quiet_a.sum())} frame dev={dev[quiet_a].mean():.4f} "
              f"motion={motb[quiet_a].mean():.4f}")
        print(f"  >>> dev nói/im = {dev[say_a].mean()/max(dev[quiet_a].mean(),1e-9):.2f}x | "
              f"motion nói/im = {motb[say_a].mean()/max(motb[quiet_a].mean(),1e-9):.2f}x")

    if args.events and os.path.isfile(args.events):
        with open(args.events, encoding="utf-8") as f:
            ev_raw = json.load(f)
        ev = {"IM trước": tuple(ev_raw["idle_pre_frames"]),
              "NÓI": tuple(ev_raw["speech_window_frames"]),
              "IM sau": tuple(ev_raw["idle_post_frames"])}
        print(f"  clip kiểm soát: {ev_raw['file']} | câu nói: {ev_raw['text']}")
        window_stats("motion", motb, ev)
        window_stats("dev   ", dev, ev)
        lo = ev["NÓI"]
        quiet = np.concatenate([np.arange(*ev["IM trước"]), np.arange(*ev["IM sau"])])
        quiet = quiet[quiet < n]
        say = np.arange(lo[0], min(lo[1], n))
        if len(quiet) and len(say):
            print(f"  >>> tỷ lệ dev lúc nói / lúc im = {dev[say].mean()/max(dev[quiet].mean(),1e-9):.2f}x"
                  f"  ({dev[say].mean():.4f} so với {dev[quiet].mean():.4f})")

    order = np.argsort(dev if dev.max() > 0 else motb)
    montage(frames, boxes, offset, r0, r1, sorted(order[-8:].tolist()),
            sorted(order[:8].tolist()), audio,
            os.path.join(ROOT, "docs", f"lipsync_montage_{os.path.splitext(os.path.basename(args.video))[0]}.png"),
            dev=dev)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        t = np.arange(n) / FPS
        fig, ax = plt.subplots(figsize=(11, 4.2))
        ax.plot(t, detrend(motb, 25), lw=1, color="#c0392b", label="mouth motion")
        ax.plot(t, detrend(dev, 25) * (np.abs(detrend(motb, 25)).mean() / (np.abs(detrend(dev, 25)).mean() + 1e-9)),
                lw=1, color="#e67e22", alpha=0.8, label="deviation vs source (scaled)")
        ax.plot(t, detrend(audio, 25) * (np.abs(detrend(motb, 25)).mean() / (np.abs(detrend(audio, 25)).mean() + 1e-9)),
                lw=1, color="#2c3e50", alpha=0.6, label="audio envelope (scaled)")
        ax.set_title(f"{os.path.basename(args.video)}  r(motion)={rb[0]:.2f}  r(dev)={rd[0]:.2f}")
        ax.set_xlabel("giây")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.25)
        png = os.path.join(ROOT, "docs", f"lipsync_{os.path.splitext(os.path.basename(args.video))[0]}.png")
        fig.tight_layout()
        fig.savefig(png, dpi=110)
        print(f"  -> {png}")
    except ImportError:
        print("  (thiếu matplotlib, bỏ qua biểu đồ)")

    out = {
        "video": os.path.basename(args.video), "avatar": args.avatar, "frames": n,
        "align_offset": offset, "align_votes": f"{votes}/{ballot}",
        "mouth_band_rows": [r0, r1], "band_source": which,
        "r_motion": round(rb[0], 3), "lag_motion": rb[1],
        "r_deviation": round(rd[0], 3), "lag_deviation": rd[1],
        "dev_mean": round(float(dev.mean()), 4), "dev_p95": round(float(np.percentile(dev, 95)), 4),
    }
    jpath = os.path.join(ROOT, "docs", f"lipsync_{os.path.splitext(os.path.basename(args.video))[0]}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  -> {jpath}")


if __name__ == "__main__":
    main()
