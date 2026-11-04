"""Kiểm tra môi trường P0: torch+CUDA nhận GTX 1650, weights/avatar đúng chỗ."""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LT = os.path.join(ROOT, "vendored", "LiveTalking")

ok = True

try:
    import torch
except ImportError:
    print("FAIL: torch chưa cài (chạy pip install theo README)")
    sys.exit(1)

print(f"torch {torch.__version__}")
if not torch.cuda.is_available():
    print("FAIL: torch.cuda.is_available() = False — sai bản torch/driver")
    sys.exit(1)

props = torch.cuda.get_device_properties(0)
print(f"GPU: {props.name}, VRAM {props.total_memory / 2**30:.1f} GiB")
print(f"CUDA runtime: {torch.version.cuda}")

ckpt = os.path.join(LT, "models", "wav2lip.pth")
if os.path.exists(ckpt):
    size_mb = os.path.getsize(ckpt) / 2**20
    print(f"wav2lip.pth: OK ({size_mb:.0f} MB)")
    if size_mb < 50:
        print("FAIL: file quá nhỏ, có vẻ là HTML lỗi tải")
        ok = False
else:
    print(f"FAIL: thiếu {ckpt}")
    ok = False

avatars_dir = os.path.join(LT, "data", "avatars")
found = []
for name in os.listdir(avatars_dir):
    d = os.path.join(avatars_dir, name)
    need = [os.path.join(d, "coords.pkl"), os.path.join(d, "full_imgs"), os.path.join(d, "face_imgs")]
    if all(os.path.exists(p) for p in need):
        n_frames = len(os.listdir(need[1]))
        found.append((name, n_frames))
if found:
    for name, n in found:
        print(f"avatar OK: {name} ({n} frames)")
else:
    print("FAIL: không có avatar hợp lệ trong data/avatars")
    ok = False

sys.exit(0 if ok else 1)
