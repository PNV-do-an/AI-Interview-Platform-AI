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

#### Option A: Docker (Recommended)

```bash
# Build image
docker build -t hiremind-ai-service .

# Run container
docker run -d \
  --name hiremind-ai \
  --gpus all \
  -p 8010:8010 \
  -p 8020:8020 \
  -e AI_AVATAR_SERVER=http://livetalking:8010 \
  -e AI_ALLOWED_ORIGIN=* \
  hiremind-ai-service

# Wait 30 seconds for warmup
# Test health check
curl http://localhost:8020/health
```

#### Option B: Colab Free Tier

See [Colab Deployment Guide](../docs/colab-deployment-guide.md) for complete instructions.

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_AVATAR_SERVER` | `http://livetalking:8010` | LiveTalking engine URL |
| `AI_ALLOWED_ORIGIN` | `*` | CORS allowed origin |
| `AI_STT_MODEL` | `small` | Whisper model: tiny/base/small |
| `AI_LLM_PROVIDER` | `template` | template/openai/vllm |
| `AI_SESSION_TTL_MIN` | `180` | Session TTL in minutes |
| `MAX_SESSION` | `5` | Max concurrent sessions |

### Config Files

- `config/livetalking.yaml` - LiveTalking engine settings
- `.env.example` - Environment variables template

## 📋 API Endpoints

### Health & Status

```http
GET /health
Returns: STT model info, max turns, active sessions
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

- **[Spec 012 Avatar Interview API]**(../../specs/012-avatar-interview-api/spec.md) - Backend contract
- **[P1 AI Service Results]**(../../docs/P1-ai-service.md) - Detailed performance metrics
- **[Colab Deployment Guide]**(../../docs/colab-deployment-guide.md) - Step-by-step setup
- **[Deployment Checklist]**(../../docs/DEPLOYMENT_CHECKLIST.md) - Verification steps

## 🛠️ Development

### Directory Structure

```
AI-Interview-Platform-AI/
├── app/
│   ├── main.py           # FastAPI server
│   ├── avatar.py         # LiveTalking client
│   ├── sessions.py       # Session management
│   ├── stt.py            # Speech-to-text
│   ├── llm.py            # Question generator
│   ├── audio.py          # Audio processing
│   └── config.py         # Configuration
├── scripts/
│   ├── p1_ai_service_e2e.py  # End-to-end test
│   ├── p1_stt_cost.py        # STT cost analysis
│   ├── p1_tts_spread.py      # TTS latency test
│   └── colab_keepalive.py    # Colab session ping
├── vendored/
│   └── LiveTalking/      # Avatar engine (external)
├── config/
│   └── livetalking.yaml  # LiveTalking config
├── Dockerfile
├── requirements-ai.txt
└── run_ai_server.py      # Launcher script
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

- **Documentation**: See `/docs/` folder
- **Issues**: Check `/specs/012-avatar-interview-api/spec.md`
- **Hardware Requirements**: See `hardware-gtx1650-4gb.md`
- **Deployment Help**: See `DEPLOYMENT.md`

---

**Created**: 2026-10-26  
**Tested On**: Google Colab T4 GPU  
**Status**: Ready for production demo 🚀
