# 🎥 Hướng dẫn Setup Video Call AI Interview

## Tổng quan

Hệ thống hỗ trợ 2 chế độ phỏng vấn với AI:

### Mode 1: Browser TTS (HOẠT ĐỘNG NGAY - Không cần GPU)
- ✅ Hoạt động trên Vercel free tier
- ✅ Không cần camera, chỉ cần micro
- ✅ AI đọc câu hỏi bằng browser's speechSynthesis API
- ❌ Không có video avatar thật (chỉ text + voice)

### Mode 2: LiveTalking Avatar (Yêu cầu GPU server/Colab)
- ✅ Avatar nói video thật qua WebRTC
- ✅ Có lip-sync tự nhiên
- ✅ Camera & microphone enabled
- ⚠️ Cần GPU server hoặc Google Colab (free)

---

## 🔧 Cách Deploy Mode 2 - LiveTalking Avatar

### Option A: Google Colab (FREE - Recommended)

**Bước 1: Mở notebook của repo AI**
```
https://colab.research.google.com/github/PNV-do-an/AI-Interview-Platform-AI/blob/main/colab-avatar-hls.ipynb
Chọn Runtime → Change runtime type → Hardware accelerator: GPU T4
```

**Bước 2: Chạy theo thứ tự**
- Cell 1: clone `AI-Interview-Platform-AI` vào `/content/ai`
- Cell 2: `scripts/colab_avatar.sh` — cài deps, tải weights, build avatar pack, dựng
  LiveTalking (rtcpush) → MediaMTX (HLS) → cloudflared → AI service → cloudflared
- Cell 3: in 2 URL public + `curl /health`
- Cell 4: keepalive (giữ phiên Colab, chạy cuối cùng và để nguyên)

Không chạy Docker trong Colab: WebRTC thuần của LiveTalking cần UDP thẳng tới trình duyệt mà
Colab không cho inbound, nên chuỗi đi qua HLS. Lý do + số đo: `docs/AVATAR-HLS-FREE.md`.

**Bước 3: Config vào Vercel Dashboard**
```
1. Truy cập: https://vercel.com/dashboard
2. Chọn project: ai-interview
3. Settings → Environment Variables
4. Sửa variable:
   - Name: REACT_APP_AI_SERVICE_URL
   - Value: [URL AI service tunnel in ra ở cell 3, = nội dung /content/ai_url.txt]
5. Redeploy (REACT_APP_* là biến build-time của CRA, đổi URL là phải build lại)
```

**Bước 4: Test**
```
1. Mở: https://aiinterview-vn.vercel.app/mock-interviews
2. Chọn "LiveTalking Avatar (Real)" → vào phòng
3. Bấm "Bật tiếng avatar" một lần (Chrome chặn autoplay có tiếng)
4. Thấy khung video có hình avatar + footer "• Giọng đọc: avatar LiveTalking" là THÀNH CÔNG
```

### Option B: Local Machine (Nếu có GPU mạnh)

```bash
cd /path/to/AI-Interview-Platform-AI

# Build Docker image
docker build -t hiremind-ai-service .

# Run container with GPU support
docker run -d \
  --name hiremind-ai \
  --gpus all \
  -p 8010:8010 \
  -p 8020:8020 \
  -e AI_AVATAR_SERVER=http://livetalking:8010 \
  -e AI_ALLOWED_ORIGIN=https://localhost:3000 \
  hiremind-ai-service

# Get local URL
echo http://localhost:8020

# Config FE's .env.production:
REACT_APP_API_URL=http://localhost:8081
REACT_APP_AI_SERVICE_URL=http://localhost:8020
```

### Option C: Cloud GPU (GCP Vertex AI - $0.50/hr)

Xem chi tiết trong file `DEPLOYMENT.md` phần **Option B: Google Cloud Vertex AI**

---

## 💰 Chi phí so sánh

| Method | GPU Cost | Storage | Bandwidth | Monthly |
|--------|----------|---------|-----------|---------|
| **Google Colab Free** | $0 | $0 | $0 | **$0** ✅ |
| GCP Spot Instance | ~$0.15/hr | $5 | Included | ~$115 |
| GCP Regular VM | ~$0.50/hr | $5 | Included | ~$370 |

→ **Khuyến nghị:** Dùng Google Colab FREE cho testing/demo
→ Production: Upgrade lên GCP Spot khi có user thật

---

## 📊 Testing Checklist

Sau khi setup xong, test các bước sau:

### Step 1: Start Session
```
✅ Giao diện hiển thị nút "LiveTalking Avatar"
✅ Select mode = 'avatar' thay vì 'text'
✅ Navigate vào trang session
```

### Step 2: Connection
```
✅ Hiển thị thông báo "Đang kết nối với LiveTalking Avatar..."
✅ Nhận được WebSocket connection
✅ Avatar bắt đầu xuất hiện trên màn hình
```

### Step 3: Question Flow
```
✅ Avatar nói question (voice + video lip-sync)
✅ Input area mở để trả lời
✅ Microphone permission requested (nếu có)
```

### Step 4: Answer & Continue
```
✅ Nhập answer text
✅ Click "Next Turn" 
✅ BE nhận transcript entry
✅ Avatar hỏi question tiếp theo
```

### Step 5: End Assessment
```
✅ Sau 40 turns OR click Finish
✅ Form self-assessment rubric (5 dimensions)
✅ Submit → Redirect to result page
```

---

## 🐛 Troubleshooting

### Error: "AI service URL chưa cấu hình"
**Cause:** Chưa set `REACT_APP_AI_SERVICE_URL` trong Vercel dashboard  
**Fix:**
1. Deploy AI service trên Colab/local/cloud
2. Copy URL tunnel (cloudflared — nội dung `/content/ai_url.txt` khi chạy notebook)
3. Vào Vercel Dashboard → Settings → Environment Variables
4. Add key `REACT_APP_AI_SERVICE_URL` = your_url
5. Redeploy frontend

### Error: "No GPU detected" khi build Docker
**Cause:** Môi trường không có GPU passthrough  
**Fix:**
- Local: Install NVIDIA Container Toolkit
- Colab: Tự động có T4 GPU
- Cloud: Chọn instance type có GPU

### Error: Port 8020 already in use
**Cause:** Cổng đang bị process khác chiếm  
**Fix:**
```bash
# Check what's using the port
netstat -ano | findstr ":8020"

# Stop conflicting process OR change port in docker-compose.yml
```

### Error: OOM (Out of Memory)
**Cause:** LiveTalking + STT nặng RAM/GPU  
**Fix:**
- Giảm batch_size: Edit `config/livetalking.yaml`, set `batch_size: 8`
- Dùng model nhỏ hơn: `AI_STT_MODEL=base` hoặc `tiny`

---

## 🚀 Deployment Commands Summary

### Frontend (Vercel)
```bash
# Already deployed on dev branch
git push origin dev
# Vercel sẽ auto-deploy trong 1-2 phút
```

### Backend Spring Boot (Render)
```bash
cd /path/to/AI-Interview-Platform-BE
git push origin dev
# Render auto-deploy from master/main branch
```

### Python AI Service (repo AI-Interview-Platform-AI)
```bash
# Colab T4, 0đ, không Docker (đường đã đo — dùng cho staging)
bash scripts/colab_avatar.sh

# Local có GPU
docker compose up --build

# Hoặc chạy thẳng
python run_ai_server.py
```

---

## 📝 Environment Variables

### Frontend

`.env.production` trong repo FE để `localhost` cho dev. Bản staging lấy giá trị từ **Vercel
dashboard → Settings → Environment Variables** (CRA không cho đổi lúc chạy):

```env
REACT_APP_API_URL=https://ai-interview-backend-staging.onrender.com
REACT_APP_AI_SERVICE_URL=https://<tunnel-ai-service>
```

Đổi `REACT_APP_AI_SERVICE_URL` là **phải redeploy** vì nó được bake lúc build; riêng `mediaUrl`
(HLS) FE đọc động từ `GET /health` nên tunnel HLS đổi cũng không cần build lại.

### AI Service (env, xem `app/config.py`)
```env
AI_AVATAR_SERVER=http://127.0.0.1:8010   # docker compose: đổi thành http://livetalking:8010
AI_AVATAR_ID=vn_interviewer_v1
AI_MEDIA_URL=                      # URL HLS public (tunnel) — rỗng thì FE phải nối WebRTC
AI_MAX_TURNS=40
AI_RUBRIC_VERSION=2026-10-v1
AI_HOST=0.0.0.0
AI_PORT=8020
AI_ALLOWED_ORIGIN=https://your-app.vercel.app
```

---

## 🔗 Useful Links

- **AI service Repo (repo này):** https://github.com/PNV-do-an/AI-Interview-Platform-AI
- **Backend Repo:** https://github.com/PNV-do-an/AI-Interview-Platform-BE
- **Frontend Repo:** https://github.com/PNV-do-an/AI-Interview-Platform-FE
- **Deployment Guide:** `DEPLOYMENT.md`
- **Đường HLS đã đo + số liệu:** `docs/AVATAR-HLS-FREE.md`
- **Colab notebook:** `colab-avatar-hls.ipynb`
- **Spec 012 (hợp đồng BE giữ):** https://github.com/PNV-do-an/AI-Interview-Platform-BE/blob/dev/specs/012-avatar-interview-api/spec.md

---

## ✨ Next Steps

1. **Setup AI Service trên Colab** (miễn phí)
2. **Config Vercel environment variables**
3. **Test full interview flow**
4. **Monitor performance & logs**
5. **Deploy to production cloud** (khi cần)

Có vấn đề? Xem mục **Troubleshooting** ở trên, `docs/AVATAR-HLS-FREE.md` (các số đã đo) hoặc tạo
issue trên GitHub repo `AI-Interview-Platform-AI`.