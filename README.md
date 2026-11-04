# 🚀 AI Interview Platform - AI Service (LiveTalking Avatar)

**Hệ thống phỏng vấn video call với avatar người thật nói tiếng Việt**

## 🎯 Features

- ✅ **LiveTalking Avatar Engine**: Avatar người Việt với giọng HoaiMy (tổng hợp Edge-TTS)
- ✅ **WebRTC Real-time Streaming**: Video call 2 chiều, lip-sync chính xác
- ✅ **Speech-to-Text (STT)**: faster-whisper nhận diện giọng nói tiếng Việt
- ✅ **Question Generation**: LLM tự động sinh câu hỏi theo JD công việc
- ✅ **Rubric Scoring**: Chấm điểm 5 tiêu chí {chuyenMon, duAn, tuDuy, truyenDat, mucKhop}
- ✅ **Transcript Editing**: Ứng viên có thể sửa transcript trước khi chốt

## 🏗 Architecture

```
┌─────────────────────────────────────┐
│     LiveTalking Engine (:8010)      │
│   - Avatar video render             │
│   - Lip-sync synchronization        │
│   - WebRTC peer connection          │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    FastAPI Orchestration (:8020)    │
│   - Session management              │
│   - Question generation (LLM)       │
│   - Speech recognition (STT)        │
│   - Rubric evaluation               │
└─────────────────────────────────────┘
```

## 📦 Installation

### Prerequisites

- GPU ≥ 4GB VRAM (GTX 1650 trở lên recommended)
- RAM ≥ 10GB system memory
- Docker 24.0+ with NVIDIA Container Toolkit
- Python 3.11+

### Quick Start

#### Option A: Colab free (0đ — đường staging đang dùng)

Mở `colab-avatar-hls.ipynb` trên Colab T4 và chạy lần lượt 4 cell code (2 cell markdown còn lại là
hướng dẫn), hoặc tay:

```bash
AI_ROOT=/content/ai FE_ORIGIN=https://aiinterview-vn.vercel.app bash scripts/colab_avatar.sh
```

Script dựng chuỗi `LiveTalking (rtcpush) → MediaMTX (HLS) → cloudflared → AI service → cloudflared`
và in hai URL public. Lý do bắt buộc đi qua HLS: WebRTC thuần cần UDP thẳng từ máy chủ tới trình
browser, mà Colab/tunnel HTTP không chuyển được UDP — xem `docs/AVATAR-HLS-FREE.md`.

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_AVATAR_SERVER` | `http://127.0.0.1:8010` | LiveTalking engine URL (`http://livetalking:8010` khi chạy 2 container rời trong docker-compose) |
| `AI_AVATAR_ID` | `vn_interviewer_v1` | Avatar pack id (build bằng `scripts/make_avatar.py`) |
| `AI_MEDIA_URL` | *(rỗng)* | URL HLS public của avatar; có giá trị thì FE phát HLS, rỗng thì FE bắt tay WebRTC qua `/avatar/offer` |
| `AI_ALLOWED_ORIGIN` | `http://localhost:3000` | CORS allowed origin — đặt đúng origin staging |
| `AI_STT_MODEL` | `small` | Whisper model: tiny/base/small |
| `AI_STT_DEVICE` / `AI_STT_COMPUTE` | `cpu` / `int8` | STT chạy CPU vì LiveTalking giữ hết VRAM 4GB |
| `AI_LLM_PROVIDER` | `template` | template/openai/vllm |
| `AI_MAX_TURNS` | `40` | Trần lượt của một phiên (khớp BE spec 012) |
| `AI_SESSION_TTL_MIN` | `180` | Session TTL in minutes |
| `AI_HOST` / `AI_PORT` | `0.0.0.0` / `8020` | Nơi FastAPI lắng nghe |
| `MAX_SESSION` | `5` | Max concurrent sessions |

### Config Files

- `config/livetalking.yaml` - LiveTalking engine settings (rtcpush/HLS)
- `config/livetalking_static.yaml` - LiveTalking engine settings (static mp4)
- `docs/AVATAR-HLS-FREE.md` - Lý do + các số đã đo của đường HLS trên Colab

## 📋 API Endpoints

### Health & Status

```http
GET /health
Returns: {status, avatarServer, avatarId, mediaUrl, avatarSessions, sttModel, llmProvider,
          openSessions, maxTurns, rubricVersion}
`mediaUrl` rỗng = host chỉ nói được WebRTC; có giá trị = FE phát HLS, không cần bắt tay /offer.
`avatarSessions: -1` = AI service sống nhưng không với tới LiveTalking.
```

### Avatar WebRTC

```http
POST /api/v1/ai/avatar/offer
Body: { offerSdp: string }
Response: { answerSdp: string, avatarSessionId: string }
```

### Interview Session

```http
POST /api/v1/ai/session
Body: { maxTurns: number, rubricVersion: string }
Response: { sessionId: string }

GET /api/v1/ai/session/{id}/question?questionIndex
Returns: Current question text and index

POST /api/v1/ai/session/{id}/answer
Body: { questionIndex, answerText, confirm: bool }
Response: Next question generated

POST /api/v1/ai/session/{id}/answer/audio
Body: multipart/form-data { file: audio.wav }
Response: Transcript from STT + next question

DELETE /api/v1/ai/session/{id}
Action: Delete session and transcript
```

### Evaluation

```http
POST /api/v1/ai/session/{id}/evaluate
Body: { chuyenMon: int, duAn: int, tuDuy: int, truyenDat: int, mucKhop: int, rubricVersion: string }
Response: Overall score + feedback
```

### Admin APIs

```http
GET /api/admin/sessions
Returns: All active sessions list
```

## 🎯 Usage Flow

### 1. Establish WebRTC Connection

```typescript
const sdpOffer = await generateWebRTCOffer();

const offerResponse = await fetch('/api/v1/ai/avatar/offer', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ offerSdp })
});

const { answerSdp, avatarSessionId } = await offerResponse.json();
// Connect SDP to RTCPeerConnection
```

### 2. Create Interview Session

```typescript
const sessionResponse = await fetch('/api/v1/ai/session', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    maxTurns: 40,
    rubricVersion: '2026-10-v1'
  })
});

const { sessionId } = await sessionResponse.json();
```

### 3. Ask Questions

```typescript
// Get current question (avatar speaks)
const questionResponse = await fetch(
  `/api/v1/ai/session/${sessionId}/question?questionIndex=0&ask=true`
);

const { questionText, speak } = await questionResponse.json();
// Display subtitles, play TTS audio
```

### 4. Collect Answers

**Option A: Text Answer**

```typescript
await fetch(`/api/v1/ai/session/${sessionId}/answer`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    questionIndex: 0,
    answerText: "User typed response...",
    confirm: true
  })
});
```

**Option B: Audio Answer**

```typescript
const audioBlob = await recordAudio(); // 6-10 seconds

const formData = new FormData();
formData.append('file', audioBlob);
formData.append('questionIndex', '0');
formData.append('confirm', 'false');

const response = await fetch(
  `/api/v1/ai/session/${sessionId}/answer`,
  { method: 'POST', body: formData }
);

const { transcript, confirmed } = await response.json();
// Show transcript for editing if confirmed=false
```

### 5. Finish & Evaluate

```typescript
// End interview
await fetch(`/api/v1/ai/session/${sessionId}/finish`, {
  method: 'POST'
});

// Submit rubric scoring
await fetch(`/api/v1/ai/session/${sessionId}/evaluate`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    chuyenMon: 85,
    duAn: 78,
    tuDuy: 92,
    truyenDat: 88,
    mucKhop: 95,
    rubricVersion: '2026-10-v1'
  })
});

// Get report
const report = await fetch(`/api/v1/ai/session/${sessionId}/transcript`);
const { questions, answers } = await report.json();
```

## 🧪 Testing

### End-to-End Test Script

```bash
# Run automated test
PYTHONIOENCODING=utf-8 python scripts/p1_ai_service_e2e.py
```

Expected results:
- GET /health → 0.01s ✓
- POST /avatar/offer → 6.16s ✓
- GET /question → 0.04s ✓
- POST /answer → 10.30s (with live avatar) ✓
- POST /evaluate → 0.01s ✓
- DELETE /session → 0.00s ✓

### Manual Testing

```bash
# Install dependencies
pip install -r requirements-ai.txt

# Run test script
python scripts/p0_webrtc_test.py
```

## 📊 Performance Metrics

Based on tests on Google Colab T4 GPU:

| Metric | Value | Notes |
|--------|-------|-------|
| Avatar startup | ~40s | First load, model warmup |
| Question generation | 0.04s | With cached prompt |
| Audio STT (6s) | 10.30s | With live avatar rendering |
| Text transcription | <1s | Pure STT without avatar |
| Rubric evaluation | 0.01s | Rule-based scoring |
| Max concurrent users | 5 | Configurable |

**Note**: STT accuracy on Vietnamese tech terms: ~85%
- Terms like "Redis" may transcribe as "REST" or "rết"
- Feature to edit transcript before finalizing required

## 🚨 Limitations & Known Issues

1. **GPU Required**: Cannot run on CPU-only environments
2. **Memory Usage**: ~8GB RAM minimum (10GB recommended)
3. **Voice Quality**: Edge-TTS occasional silent utterances (1/7 cases)
4. **Vietnamese ASR**: Tech terms need manual correction option
5. **Session Timeout**: Colab free tier ~12 hours continuous use

## 🔐 Security Notes

- No credentials stored in codebase
- All config via environment variables
- Audio files never persisted to disk (memory only)
- Session data ephemeral, deleted on session end
- JWT authentication required for BE integration

## 💰 Cost Estimates

### Google Colab Free Tier
- GPU: $0/hr (T4 Tensor Core)
- Storage: Ephemeral (lost on disconnect)
- Bandwidth: Within fair use policy
- **Total: $0/month** (testing/demo only)

### Production Deployment

**Google Cloud Spot Instance:**
- n1-standard-2 + T4 GPU
- ~$0.15/hr = ~$110/month
- Recommended for beta users

**Render Container (GPU):**
- Basic plan with GPU
- ~$75/month
- Auto-scaling ready

**Full Production Cluster:**
- Multiple GPU instances
- Load balancer + CDN
- ~$360+/month
- Enterprise SLA

## 🔄 Migration Path

1. **Phase 1: Testing** (Current)
   - Google Colab Free
   - ngrok tunnel for access
   - Goal: Validate functionality

2. **Phase 2: Beta**
   - GCP Spot Instance
   - Own domain (replace ngrok)
   - Estimated cost: $110/month

3. **Phase 3: Scale**
   - Kubernetes cluster
   - Multi-region deployment
   - Auto-scaling GPU instances
   - Estimated cost: $360+/month

## 📚 Documentation

- `docs/AVATAR-HLS-FREE.md` - vì sao Colab/tunnel bắt buộc đi HLS, các số đã đo 31/10
- `DEPLOYMENT.md` - Colab (0đ) / GCP có IP public / Docker local
- `VIDEO_CALL_SETUP.md` - nối phòng avatar vào staging, checklist từng bước, troubleshooting
- `colab-avatar-hls.ipynb` - notebook dựng cả chuỗi trên một máy Colab
- Spec 012 (hợp đồng BE giữ): https://github.com/PNV-do-an/AI-Interview-Platform-BE/blob/dev/specs/012-avatar-interview-api/spec.md

## 🛠️ Development

### Directory Structure

```
AI-Interview-Platform-AI/
├── app/
│   ├── main.py           # FastAPI server (:8020) — biên HTTP của AI service
│   ├── avatar.py         # Client LiveTalking (:8010)
│   ├── sessions.py       # Store phiên + orchestrator hỏi/đáp
│   ├── stt.py            # faster-whisper (CPU int8)
│   ├── llm.py            # Sinh câu hỏi theo JD + chấm rubric
│   ├── audio.py          # Giải mã audio frontend gửi lên
│   └── config.py         # Toàn bộ cấu hình từ biến AI_*
├── scripts/
│   ├── colab_avatar.sh       # Bring-up cả chuỗi LiveTalking→MediaMTX→cloudflared trên Colab
│   ├── patch_rtcpush_whip.py # Vá LiveTalking để MediaMTX nhận WHIP
│   ├── run_server.py         # Khởi động LiveTalking theo config yaml
│   ├── make_avatar.py        # Build avatar pack từ ảnh/mp4 nguồn trong assets/
│   ├── p0_*.py / p1_*.py     # Đo lip-sync, STT, TTS, e2e
│   └── colab_keepalive.py    # Giữ phiên Colab
├── docs/AVATAR-HLS-FREE.md   # Vì sao bắt buộc HLS + các số đã đo
├── colab-avatar-hls.ipynb    # Notebook dựng avatar cho staging (0đ)
├── config/livetalking*.yaml  # Config engine avatar
├── vendored/LiveTalking/     # Không vào git; clone lúc build/Chạy script
├── Dockerfile + entrypoint.sh    # Một container chạy cả :8010 và :8020
├── docker-compose.yml        # Ai-service + livetalking (GPU host có IP public)
├── DEPLOYMENT.md / VIDEO_CALL_SETUP.md
├── requirements-ai.txt
└── run_ai_server.py          # Launcher FastAPI
```

### Running Locally

```bash
# Start LiveTalking engine (port 8010)
python scripts/run_server.py \
  --config config/livetalking.yaml \
  --transport webrtc \
  --stun '' \
  --listenport 8010

# Start FastAPI wrapper (port 8020)
python run_ai_server.py
```

## 🤝 Contributing

This is a specialized service for the AI Interview Platform project.
For issues related to deployment or configuration, see documentation above.

## 📄 License

Internal use only. See parent repository for license details.

## 🆘 Support

- **Vì sao staging phải đi qua HLS (số đã đo)**: `docs/AVATAR-HLS-FREE.md`
- **Deploy**: `DEPLOYMENT.md`, `VIDEO_CALL_SETUP.md`, `colab-avatar-hls.ipynb`
- **Hợp đồng API / nghiệp vụ**: spec 012 nằm ở repo BE —
  https://github.com/PNV-do-an/AI-Interview-Platform-BE/blob/dev/specs/012-avatar-interview-api/spec.md

---

**Created**: 2026-10-26  
**Tested On**: Google Colab T4 GPU  
**Status**: Ready for production demo 🚀
