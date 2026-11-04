#!/usr/bin/env bash
# Bring-up toàn bộ chuỗi avatar trên Google Colab (T4 free, $0, KHÔNG cần Docker).
#
#   bash scripts/colab_avatar.sh
#
# Kiến trúc đã đo ngày 31/10 (xem docs/AVATAR-HLS-FREE.md):
#   LiveTalking (--transport rtcpush) --WHIP/http--> MediaMTX --HLS/https--> cloudflared --> trình duyệt
#   AI service (FastAPI 8020) ---------------------http--> cloudflared -------------------> trình duyệt
# Sở dĩ phải vậy: WebRTC thuần của LiveTalking cần UDP đi thẳng từ máy chủ tới trình duyệt,
# còn Colab chỉ có HTTP ra ngoài. rtcpush push vào MediaMTX ở 127.0.0.1 (loopback, UDP nội bộ
# vẫn chạy được), trình duyệt chỉ kéo HLS qua HTTPS.
set -euo pipefail

AI_ROOT="${AI_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
LT="$AI_ROOT/vendored/LiveTalking"
AVATAR_ID="${AVATAR_ID:-vn_interviewer_v1}"
MODEL="${MODEL:-wav2lip}"
HLS_PATH="${HLS_PATH:-avatar}"
FE_ORIGIN="${FE_ORIGIN:-https://aiinterview-vn.vercel.app}"
LOG_DIR="${LOG_DIR:-/content/logs}"
URLS_FILE="${URLS_FILE:-/content/avatar_urls.txt}"
PORT_LT=8010
PORT_MTX_HLS=8888
PORT_MTX_WHIP=8889
PORT_AI=8020

mkdir -p "$LOG_DIR"

step() { printf '\n=== %s ===\n' "$*"; }

wait_http() { # wait_http <url> <giây-chờ> <mô-tả>
  local url="$1" limit="$2" what="$3" i
  # -L là bắt buộc: MediaMTX trả 302 set-cookie trước khi playlist thật, nên không theo
  # redirect thì curl báo "ok" cả khi chưa có stream.
  for i in $(seq 1 "$limit"); do
    if curl -fsSL -m 3 -o /dev/null "$url"; then return 0; fi
    sleep 1
  done
  echo "Hết ${limit}s mà $what vẫn chưa trả 200: $url" >&2
  return 1
}

public_url_of() { # public_url_of <log> -> in ra URL trycloudflare đầu tiên
  grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$1" | head -1
}

tunnel() { # tunnel <cổng> <log> <timeout-giây> -> in ra URL public
  local port="$1" log="$2" limit="${3:-60}" url="" i
  (nohup cloudflared tunnel --url "http://127.0.0.1:$port" --no-autoupdate > "$log" 2>&1 &)
  for i in $(seq 1 "$limit"); do
    url="$(public_url_of "$log")"
    [ -n "$url" ] && { echo "$url"; return 0; }
    sleep 1
  done
  echo "cloudflared không in URL trong $limit+s (xem $log)" >&2; return 1
}

nvidia-smi -L || { echo "Colab chưa bật GPU: Runtime → Change runtime type → T4" >&2; exit 1; }

# vendored/ không vào git (.gitignore loại) nên không có nguồn LiveTalking trong bản clone.
# Kéo thẳng từ upstream, pin đúng commit đã kiểm chứng trên máy local.
step "0/8 LiveTalking nguon (lipku/LiveTalking)"
LT_PIN=c7269433a2b6ecebcd9342445d2ecc882c98b0da
if [ ! -f "$LT/requirements.txt" ]; then
  mkdir -p "$AI_ROOT/vendored"
  rmdir "$LT" 2>/dev/null || true
  git clone -q https://github.com/lipku/LiveTalking.git "$LT"
  git -C "$LT" checkout -q "$LT_PIN"
fi
git -C "$LT" rev-parse HEAD | cat

step "1/8 cài dependencies (torch đã có sẵn trong Colab)"
pip install -q -r "$LT/requirements.txt"
pip install -q -r "$AI_ROOT/requirements-ai.txt"
# requirements của LiveTalking kéo theo transformers/diffusers, dễ lệch với torch của Colab.
python - <<'PY'
import torch
assert torch.cuda.is_available(), "torch không thấy CUDA — Colab chưa cấp GPU"
print(f"[ok] torch {torch.__version__} / {torch.cuda.get_device_name(0)}")
PY

step "2/8 vá rtcpush để MediaMTX nhận SDP"
python "$AI_ROOT/scripts/patch_rtcpush_whip.py"

step "3/8 tải weights (~300MB)"
mkdir -p "$LT/models"
[ -s "$LT/models/wav2lip.pth" ] || wget -q --show-progress -O "$LT/models/wav2lip.pth" \
  https://huggingface.co/shibing624/ai-avatar-wav2lip/resolve/main/wav2lip.pth
S3FD="$LT/avatars/wav2lip/face_detection/detection/sfd/s3fd.pth"
[ -s "$S3FD" ] || wget -q -O "$S3FD" https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth
ls -l "$LT/models/wav2lip.pth" "$S3FD"

step "4/8 build avatar pack $AVATAR_ID"
if [ -d "$LT/data/avatars/$AVATAR_ID/face_imgs" ]; then
  echo "đã có $LT/data/avatars/$AVATAR_ID — bỏ qua"
else
  ( cd "$AI_ROOT" && python scripts/make_avatar.py --src assets/vn_interviewer_src.png --id "$AVATAR_ID" )
fi

step "5/8 MediaMTX (WHIP ingest $PORT_MTX_WHIP, HLS out $PORT_MTX_HLS)"
if [ ! -x /content/mediamtx/mediamtx ]; then
  VER="$(curl -fsS https://api.github.com/repos/bluenviron/mediamtx/releases/latest |
        grep -oP '"tag_name":\s*"v\K[0-9.]+')"
  wget -q -O /content/mtx.tgz "https://github.com/bluenviron/mediamtx/releases/download/v${VER}/mediamtx_v${VER}_linux_amd64.tar.gz"
  mkdir -p /content/mediamtx && tar -xzf /content/mtx.tgz -C /content/mediamtx
fi
cat > /content/mediamtx/mediamtx.yml <<YML
logLevel: info
api: yes
apiAddress: 127.0.0.1:9997
rtmp: yes
rtmpAddress: 127.0.0.1:1935
hls: yes
hlsAddress: 127.0.0.1:$PORT_MTX_HLS
hlsAllowOrigin: '*'
webrtc: yes
webrtcAddress: 127.0.0.1:$PORT_MTX_WHIP
webrtcLocalUDPAddress: 0.0.0.0:8189
webrtcAllowOrigin: '*'
YML
(cd /content/mediamtx && nohup ./mediamtx > "$LOG_DIR/mediamtx.out" 2>&1 &)
wait_http "http://127.0.0.1:$PORT_MTX_HLS/" 30 "MediaMTX"

step "6/8 LiveTalking rtcpush (push vào 127.0.0.1:$PORT_MTX_WHIP/$HLS_PATH/whip)"
(cd "$AI_ROOT" && nohup python scripts/run_server.py \
  --config "$AI_ROOT/config/livetalking.yaml" \
  --model "$MODEL" --avatar_id "$AVATAR_ID" \
  --transport rtcpush --max_session 1 \
  --push_url "http://127.0.0.1:$PORT_MTX_WHIP/$HLS_PATH/whip" \
  --listenport "$PORT_LT" > "$LOG_DIR/livetalking.log" 2>&1 &)
# rtcpush tự mở session "0" ngay lúc khởi động và push liên tục; HLS chỉ có stream khi cú push đó thành công.
wait_http "http://127.0.0.1:$PORT_MTX_HLS/$HLS_PATH/index.m3u8" 180 "luồng avatar ($HLS_PATH)"
curl -fsS -m 5 "http://127.0.0.1:$PORT_LT/api/admin/sessions" | head -c 200; echo

step "7/8 cloudflared: tunnel HTTPS cho HLS"
[ -x /usr/local/bin/cloudflared ] || wget -q -O /usr/local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x /usr/local/bin/cloudflared
HLS_URL="$(tunnel "$PORT_MTX_HLS" "$LOG_DIR/cf-hls.log")"
echo "HLS public: $HLS_URL"

step "8/8 AI service (FastAPI $PORT_AI)"
( cd "$AI_ROOT" && env \
    AI_AVATAR_SERVER="http://127.0.0.1:$PORT_LT" \
    AI_AVATAR_ID="$AVATAR_ID" \
    AI_MEDIA_URL="$HLS_URL/$HLS_PATH/index.m3u8" \
    AI_ALLOWED_ORIGIN="$FE_ORIGIN" \
    nohup python run_ai_server.py > "$LOG_DIR/ai.log" 2>&1 & )
wait_http "http://127.0.0.1:$PORT_AI/health" 60 "AI service"
curl -fsS -m 5 http://127.0.0.1:$PORT_AI/health; echo
AI_URL="$(tunnel "$PORT_AI" "$LOG_DIR/cf-ai.log")"
echo "AI service public: $AI_URL"

echo "$AI_URL" > /content/ai_url.txt
echo "$HLS_URL" > /content/hls_url.txt
cat > "$URLS_FILE" <<TXT
AI service (đặt vào Vercel env REACT_APP_AI_SERVICE_URL, rồi redeploy FE):
$AI_URL

Luồng avatar HLS (AI service tự báo qua /health, không cần cấu hình FE):
$AI_URL -> mediaUrl = $HLS_URL/$HLS_PATH/index.m3u8

Log: $LOG_DIR/{livetalking,ai,cf-ai,cf-hls}.log, $LOG_DIR/mediamtx.out
TXT
echo; cat "$URLS_FILE"
