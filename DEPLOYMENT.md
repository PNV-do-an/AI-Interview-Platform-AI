# Hướng dẫn Deploy Python AI Service (LiveTalking + FastAPI)

## Overview

Service này cung cấp avatar AI nói tiếng Việt thật, kết hợp với FastAPI orchestration layer.
Kênh media là WebRTC khi host mở được inbound UDP, hoặc HLS qua RTMP/WHIP push khi host chỉ có
HTTP public (Colab, sau NAT) — đường staging đang dùng HLS.

**Components:**
- **LiveTalking** (:8010): Avatar video engine với wav2lip lip-sync
- **FastAPI Wrapper** (:8020): API gateway cho FE, xử lý LLM/question/STT

## Prerequisites

### Hardware Requirements

| Component | GPU VRAM | RAM | Notes |
|---|---|---|---|
| LiveTalking | ≥ 4GB | 8GB | GTX 1650 trở lên |
| FastAPI | None | 2GB | CPU-only |
| **Total** | **≥ 4GB GPU** | **≥ 10GB** | Dùng chung VM nếu < 16GB VRAM |

### Software Stack

```yaml
OS: Ubuntu 22.04 LTS
GPU Driver: NVIDIA 516+ (CUDA 11.x)
Docker: 24.0+ with NVIDIA container toolkit
Python: 3.11 (venv trong container)
```

---

## Option A: Google Colab (FREE - Best for Testing)

**Đường đã kiểm chứng cho Colab là `colab-avatar-hls.ipynb` / `scripts/colab_avatar.sh`, KHÔNG phải
Docker.** Colab không cho inbound UDP nên WebRTC thuần của LiveTalking không chạy được, và Docker-in
Colab + ngrok không phải thứ đã đo; chuỗi thật đi `rtcpush → MediaMTX → HLS → cloudflared` — xem
`docs/AVATAR-HLS-FREE.md`. Các bước dưới đây chỉ còn giá trị trên máy ảo có IP public (Option B/C).

**Ưu điểm:** Miễn phí, không cần setup, GPU T4 mạnh hơn yêu cầu  
**Nhược điểm:** Giới hạn 12 giờ/session, cần chạy thường xuyên

### 1. Mở notebook

https://colab.research.google.com/github/PNV-do-an/AI-Interview-Platform-AI/blob/main/colab-avatar-hls.ipynb

Runtime → Change runtime type → **Hardware accelerator: T4 GPU**.

### 2. Chạy 4 cell

| Cell | Việc |
|---|---|
| 1 | clone `AI-Interview-Platform-AI` (repo public, không cần token) vào `/content/ai` |
| 2 | `AI_ROOT=/content/ai FE_ORIGIN=https://aiinterview-vn.vercel.app bash /content/ai/scripts/colab_avatar.sh` |
| 3 | in `/content/avatar_urls.txt` và `curl <AI_URL>/health` |
| 4 | keepalive nền (ping mỗi 9 phút) — chạy cuối cùng và để nguyên tab |

`colab_avatar.sh` tự làm phần còn lại: cài deps (torch của Colab, không cài lại) → vá WHIP cho
MediaMTX bằng `scripts/patch_rtcpush_whip.py` → tải `wav2lip.pth` + `s3fd.pth` → build avatar pack
`vn_interviewer_v1` → MediaMTX → LiveTalking `--transport rtcpush --max_session 1` → tunnel HLS →
AI service → tunnel AI.

### 3. Cấu hình Frontend

URL trong `/content/ai_url.txt` là `REACT_APP_AI_SERVICE_URL`: Vercel → Settings → Environment
Variables (type Production) → Redeploy. Đây là biến build-time của CRA nên đổi URL là phải build
lại; `mediaUrl` của luồng HLS thì FE đọc động từ `/health`, không cần build.

### 4. Khi session hết hạn

Colab free cắt phiên sau ~12h và quick tunnel đổi URL ⇒ lại phải sửa env + redeploy. Muốn hết cảnh
đó cần hostname ổn định (Cloudflare named tunnel + domain riêng) hoặc máy ảo có IP public ở
Option B/C.

---

## Option B: Google Cloud Vertex AI (Production Ready)

### 1. Tạo Custom Instance Template

```bash
gcloud compute instances create hiremind-ai \
  --machine-type=n1-standard-2 \
  --accelerator=count=1,type=nvidia-tesla-t4 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=100GB \
  --boot-disk-type=pd-ssd \
  --zone=us-central1-a
```

### 2. SSH vào instance

```bash
gcloud compute ssh hiremind-ai --zone=us-central1-a
```

### 3. Install dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install NVIDIA Container Toolkit
wget -P /tmp https://nvidia.github.io/libnvidia-container/gpgkey
sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg /tmp/gpgkey
curl -s -L https://nvidia.github.io/libnvidia-container/stable/docker/nvidia-container-toolkit.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install nvidia-container-toolkit -y

# Restart Docker with NVIDIA support
sudo systemctl restart docker
sudo docker info | grep -i nvidia
```

### 4. Clone và build Docker image

```bash
cd ~
git clone https://github.com/PNV-do-an/AI-Interview-Platform-AI.git
cd AI-Interview-Platform-AI

# Build image (sẽ mất 10-15 phút)
docker build -t hiremind-ai-service .

# Check image size (should be ~5GB)
docker images hiremind-ai-service
```

### 5. Run container

```bash
# AI service gọi LiveTalking chạy trong cùng container (entrypoint.sh), nên là 127.0.0.1
# chứ không phải hostname livetalking (hostname đó chỉ đúng với docker compose).
docker run -d \
  --name hiremind-ai \
  --gpus all \
  -p 8010:8010 \
  -p 8020:8020 \
  -e AI_AVATAR_SERVER=http://127.0.0.1:8010 \
  -e AI_ALLOWED_ORIGIN=https://your-vercel-app.vercel.app \
  hiremind-ai-service
```

### 6. Configure firewall

```bash
# Allow ports 80, 443, 8010, 8020
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8010/tcp
sudo ufw allow 8020/tcp
sudo ufw enable
```

WebRTC thuần còn cần **inbound UDP** từ trình duyệt ứng viên tới cổng media của LiveTalking
(không chỉ TCP 8010). Nếu không mở được UDP range, or nếu VM nằm sau NAT, dùng đường HLS như
Option A (`scripts/colab_avatar.sh`) rồi đặt `-e AI_MEDIA_URL=<url HLS public>/index.m3u8` —
FE sẽ tự phát HLS sau khi đọc `mediaUrl` từ `/health`.

### 7. Verify service is running

```bash
# Check container logs
docker logs -f hiremind-ai

# Test health endpoint
curl http://localhost:8020/health
# Expected response: {"status":"ok","avatarServer":"http://127.0.0.1:8010",...}

# Check avatar status
curl http://localhost:8010/api/admin/sessions
# Expected response: {"code":0,"msg":"ok","data":{"sessions":[]}}
```

---

## Option C: Self-hosted Local Server

### 1. Install Docker Desktop for Windows

Download từ: https://www.docker.com/products/docker-desktop/

Enable WSL 2 backend and NVIDIA GPU passthrough.

### 2. Build and run

```powershell
cd D:\AI-Interview-Platform-AI

# Build image
docker build -t hiremind-ai-service .

# Run container (map to localhost ports)
docker run -d `
  --name hiremind-ai `
  --gpus all `
  -p 8010:8010 `
  -p 8020:8020 `
  -e AI_ALLOWED_ORIGIN=http://localhost:3000 `
  hiremind-ai-service
```

**Chỉ dùng được khi máy chủ có IP public mà inbound UDP tới :8010 mở được.** `entrypoint.sh` chạy
LiveTalking với `--transport webrtc`, tức media đi UDP thẳng từ server về trình duyệt ứng viên; sau
NAT thì kênh đó không hình thành, biểu hiện là phòng báo `Không thiết lập được kênh video với avatar`.
Đi sau NAT thì phải dùng đường HLS (`scripts/colab_avatar.sh` như Option A, hoặc tự chạy
rtcpush → MediaMTX → tunnel và đặt `AI_MEDIA_URL`).

---

## Frontend Configuration

`REACT_APP_*` là biến build-time của CRA, nên bản staging lấy giá trị từ **Vercel dashboard →
project `ai-interview` → Settings → Environment Variables** (file `.env.production` trong repo FE
chỉ dùng khi build tại máy; Vercel ghi đè nó):

```env
REACT_APP_API_URL=https://your-render-backend.onrender.com/api/v1
REACT_APP_AI_SERVICE_URL=https://your-ai-server.hiremind.com
```

Đổi `REACT_APP_AI_SERVICE_URL` xong phải **Redeploy** mới có hiệu lực. Riêng `mediaUrl` của luồng
HLS thì FE đọc động từ `/health` mỗi lần vào phòng, không cần build lại.

---

## Troubleshooting

### Error: No GPU detected

```bash
# Check if Docker can see GPU
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# If this fails, reinstall NVIDIA Container Toolkit
sudo apt install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### Error: Port already in use

```bash
# Check what's using port 8010/8020
netstat -ano | findstr ":8010"
netstat -ano | findstr ":8020"

# Stop conflicting processes or change ports in .env
```

### Error: OOM (Out of Memory)

LiveTalking + STT nặng RAM. Nếu gặp OOM:
- Giảm batch_size xuống 8 (edit config/livetalking.yaml)
- Dùng model nhỏ hơn: `AI_STT_MODEL=base` hoặc `tiny`

---

## Monitoring

```bash
# Real-time GPU usage
watch -n 1 nvidia-smi

# Container logs
docker logs -f hiremind-ai

# Resource usage
docker stats hiremind-ai
```

---

## Cost Estimation

### Option A: Google Colab (FREE)
| Resource | Cost | Notes |
|---|---|---|
| GPU T4 | $0/hr | Miễn phí, giới hạn 12h/session |
| Storage | $0 | ephemeral, mất khi disconnect |
| **Total** | **$0/month** | Ideal cho testing/demo |

### Option B: Google Cloud (Production)
| Instance Type | Hourly Rate | Monthly Cost |
|---|---|---|
| n1-standard-2 + T4 | ~$0.50/hr | ~$360/month (24/7) |
| Spot/TCP instance | ~$0.15/hr | ~$110/month (24/7) |

Giảm chi phí bằng cách:
- Chỉ chạy khi cần test (Colab preferred)
- Tự động stop/start theo schedule
- Dùng spot instances cho non-critical workloads

## Migration Path

1. **Phase 1 - Testing**: Dùng Google Colab (miễn phí) để validate functionality
2. **Phase 2 - Beta**: Chuyển sang GCP Spot Instance khi có user thật (~$110/tháng)
3. **Phase 3 - Production**: Scale up với auto-scaling groups khi cần
