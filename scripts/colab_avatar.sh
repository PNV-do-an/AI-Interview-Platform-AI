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

# Tăng thời gian wait cho các bước dài
export GIT_TERMINAL_PROMPT=0
export AWS_MAX_ATTEMPTS=3

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

# daemon <log> <cwd> <lenh...>
# Cell Colab ket thuc thi tan sat doan tien trinh cua shell no, nen "nohup ... &" thoi la khong
# du: dich vu chet ngay sau do, duong tunnel tra Cloudflare 1033. setsid dua no sang session
# khac; </dev/null + redirect thu cong 3 fd cua cell de cell khong bi giu trang thai Executing.
daemon() {
  local log="$1" dir="$2"; shift 2
  local launcher=(nohup)
  command -v setsid >/dev/null 2>&1 && launcher=(setsid)
  # Chuyen huong luu trong (stdout+stderr) vao log file
  ( cd "$dir" && "${launcher[@]}" "$@" >"$log" 2>&1 < /dev/null & )
}

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
  # Strip ANSI codes trước khi grep (Colab log co chep them).
  # || true la bat buoc: grep tra 1 khi chua co URL, nen "set -eo pipefail" se giết script ngay
  # vong lap dau tien cua tunnel() — chet im lang, khong in loi.
  sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$1" 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 || true
}

# Mặc định cloudflared thử QUIC (UDP), và trên Colab nó có thể treo sau dòng "precheck complete"
# mà không bao giờ in URL. --protocol http2 ép nó dùng TCP 443, đường mà chính precheck báo
# "HTTP/2 connection successful". Vẫn cần retry vì quick tunnel đôi khi lỗi im lặng.
tunnel() { # tunnel <cổng> <log> <timeout-giây> -> in ra URL public
  local port="$1" log="$2" limit="${3:-90}" url="" attempt i
  for attempt in 1 2 3; do
    echo "[attempt $attempt] Starting cloudflared on port $port..." >&2
    
    # Start tunnel
    daemon "$log" / cloudflared tunnel --url "http://127.0.0.1:$port" \
      --no-autoupdate --protocol http2
    
    # Trong khi chờ, tail log mỗi 5s để biết cloudflared đang làm gì
    echo "[attempt $attempt] Waiting for cloudflared to mint URL (watching $log)..." >&2
    last_size=0
    
    for i in $(seq 1 "$limit"); do
      # Check if log file exists and has content
      if [ -f "$log" ]; then
        current_size=$(wc -c < "$log" 2>/dev/null || echo 0)
        
        # Nếu log mới có nội dung, show it
        if [ "$current_size" -gt "$last_size" ] && [ "$current_size" -gt 100 ]; then
          echo "--- cloudflared output so far ---" >&2
          tail -n 10 "$log" >&2
          echo "--- end of cloudflared output ---" >&2
          last_size=$current_size
        fi
        
        # Try to extract URL
        url="$(public_url_of "$log")"
        if [ -n "$url" ]; then
          echo "Cloudflared URL found!" >&2
          echo "$url"; return 0
        fi
      fi
      
      sleep 2
    done
    
    echo "cloudflared không in URL sau ${limit}s (lần thử $attempt/3, xem $log)" >&2
    pkill -f "cloudflared tunnel --url http://127.0.0.1:$port" 2>/dev/null || true
    sleep 5
  done
  echo "FATAL: không mở được tunnel cho cổng $port sau 3 lần (xem $log)" >&2
  return 1
}

nvidia-smi -L || { echo "Colab chưa bật GPU: Runtime → Change runtime type → T4" >&2; exit 1; }

# Chạy lại cell trên cùng runtime thì tiến trình lần trước vẫn giữ 8010/8020/8888/8889 và MediaMTX,
# AI service cũ sẽ trả lời bằng config/HLS URL cũ -> dẹp đúng bốn thứ script này sinh ra (theo cmdline).
step "don lan chay truoc"
# tunnel chet ngay sau cell neu launcher la nohup -> dong nay cho biet Colab co setsid khong.
echo "launcher tien trinh nen: $(command -v setsid || echo 'nohup (khong co setsid)')"
pkill -x mediamtx 2>/dev/null || true
pkill -f 'scripts/run_server.py' 2>/dev/null || true
pkill -f 'run_ai_server.py' 2>/dev/null || true
pkill -f 'cloudflared tunnel' 2>/dev/null || true
sleep 3

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

# Cài python_rtmpstream cho RTMP transport
# Thư viện này không có trên PyPI, phải build từ source lipku/python_rtmpstream
echo "[Step 1/8] Installing python_rtmpstream from source..." >&2
echo "Installing FFmpeg development libraries..." >&2
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  libavcodec-dev libavformat-dev libavutil-dev libswscale-dev

RTMP_STREAM_DIR="/content/python_rtmpstream"
if [ ! -d "$RTMP_STREAM_DIR" ]; then
  git clone -q --depth 1 https://github.com/lipku/python_rtmpstream.git "$RTMP_STREAM_DIR"
  git -C "$RTMP_STREAM_DIR" submodule update --init --recursive --depth 1
fi
# Check Python version và build tương thích
PYTHON_VER="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Building rtmp_streaming for Python $PYTHON_VER..." >&2
cd "$RTMP_STREAM_DIR/python" || { echo "FATAL: cannot cd to rtmp_stream_dir" >&2; exit 1; }

PYTHON_EXECUTABLE="$(command -v python)"
PYTHON_INC="$(python -c 'import sysconfig; print(sysconfig.get_paths()["include"])')"
# Upstream CMakeLists.txt contains paths from its original Anaconda build environment.
sed -i \
  -e "s|^set(PYTHON_EXECUTABLE .*|set(PYTHON_EXECUTABLE \"$PYTHON_EXECUTABLE\")|" \
  -e "s|^include_directories(\"/opt/anaconda3/envs/python37/include\")|include_directories(\"$PYTHON_INC\")|" \
  -e 's|^find_library(AVCODEC_LIBRARY avcodec .*|find_library(AVCODEC_LIBRARY avcodec)|' \
  -e 's|^find_library(AVFORMAT_LIBRARY avformat .*|find_library(AVFORMAT_LIBRARY avformat)|' \
  -e 's|^find_library(AVUTIL_LIBRARY avutil .*|find_library(AVUTIL_LIBRARY avutil)|' \
  -e 's|^find_library(SWSCALE_LIBRARY swscale .*|find_library(SWSCALE_LIBRARY swscale)|' \
  CMakeLists.txt
pip install -q .

python -c "import rtmp_streaming; print('[ok] rtmp_streaming OK:', rtmp_streaming.__file__)"

step "2/8 chuyển sang RTMP cho stream liên tục"
# Bỏ qua WHIP patch — dùng RTMP sẽ ổn định hơn cho avatar stream 24/7
echo "[skip] Using RTMP instead of WHIP — avoids session lifecycle issues" >&2

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

# --- 5/8 MediaMTX (RTMP ingest 1935, HLS out 8888) ---
echo "=== 5/8 MediaMTX (RTMP ingest :1935, HLS out :8888) ==="

MTX_BIN="$AI_ROOT/mediamtx/mediamtx"
MTX_CFG="$AI_ROOT/mediamtx/mediamtx.yml"
MTX_LOG="$LOG_DIR/mediamtx.log"

# Download mediamtx if not exists
if [ ! -x "$MTX_BIN" ]; then
  VER="$(curl -fsS https://api.github.com/repos/bluenviron/mediamtx/releases/latest |
        grep -oP '"tag_name":\s*"v\K[0-9.]+')"
  wget -q -O /content/mtx.tgz "https://github.com/bluenviron/mediamtx/releases/download/v${VER}/mediamtx_v${VER}_linux_amd64.tar.gz"
  mkdir -p "$AI_ROOT/mediamtx" && tar -xzf /content/mtx.tgz -C "$AI_ROOT/mediamtx"
fi

# Build minimal config chuẩn — bật RTMP để nhận continuous stream
cat > "$MTX_CFG" <<YML
logLevel: info
logDestinations: [stdout]

hls: yes
hlsAddress: :8888
hlsAllowOrigin: '*'

webrtc: yes
webrtcAddress: :8889
webrtcAllowOrigin: '*'
webrtcAdditionalHosts: [127.0.0.1]

rtmp: yes
rtmpAddress: :1935

rtsp: no
srt: no

paths:
  all_others:
    source: publisher
YML

echo "=== Mediamtx Config ===" >&2
cat "$MTX_CFG" >&2
echo "========================" >&2

# Kiểm tra binary tồn tại & chạy được
if [ ! -x "$MTX_BIN" ]; then
  echo "FATAL: không tìm thấy mediamtx binary tại $MTX_BIN" >&2
  exit 1
fi
"$MTX_BIN" --version 2>&1 | head -1

# Kiểm tra config tồn tại
if [ ! -f "$MTX_CFG" ]; then
  echo "FATAL: thiếu config $MTX_CFG" >&2
  exit 1
fi

# Dọn tiến trình cũ (dùng -f vì binary tên 'mediamtx')
pkill -f 'mediamtx' 2>/dev/null || true
sleep 1

# Khởi động
daemon "$MTX_LOG" "$AI_ROOT/mediamtx" "$MTX_BIN" "$MTX_CFG"

# Chờ tối đa 20s cho tới khi cổng 1935/8888 mở
ready=0
for i in $(seq 1 20); do
  if ss -lnt 2>/dev/null | grep -q ':1935 '; then ready=1; break; fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "FATAL: MediaMTX không mở cổng 1935 sau 20s. Log:" >&2
  tail -n 50 "$MTX_LOG" >&2 || true
  exit 1
fi
echo "MediaMTX OK (RTMP), log = $MTX_LOG"

step "6/8 LiveTalking rtmp (push vào rtmp://127.0.0.1:1935/$HLS_PATH)"

# RTMP là continuous stream, không có session lifecycle issues như WHIP
daemon "$LOG_DIR/livetalking.log" "$AI_ROOT" python scripts/run_server.py \
  --config "$AI_ROOT/config/livetalking.yaml" \
  --model "$MODEL" --avatar_id "$AVATAR_ID" \
  --transport rtmp --max_session 1 \
  --push_url "rtmp://127.0.0.1:1935/$HLS_PATH" \
  --listenport "$PORT_LT"
# RTMP push liên tục; HLS sẽ available ngay khi avatar bắt đầu render frame
echo "Waiting for HLS stream (max 60s)..." >&2
wait_http "http://127.0.0.1:$PORT_MTX_HLS/$HLS_PATH/index.m3u8" 60 "luồng avatar ($HLS_PATH)" || {
  echo "HLS không sẵn sau 60s - kiểm tra log:" >&2
  tail -n 50 "$LOG_DIR/livetalking.log" >&2 || true
  tail -n 50 "$MTX_LOG" >&2 || true
  exit 1
}
curl -fsS -m 5 "http://127.0.0.1:$PORT_LT/api/admin/sessions" | head -c 200; echo

step "7/8 cloudflared: tunnel HTTPS cho HLS"
if [ ! -x /usr/local/bin/cloudflared ]; then
  # wget -q im lang hon wget that: mot cu tai ken (Colab van thuong bi nganh toc khi di GitHub)
  # se khien script dung o day ma khong in ra dong retry nao cua tunnel() -> khong phan biet duoc
  # "tai cham" va "tunnel treo". Bu no in tien do va tu ket lieu neu 30s khong tien.
  wget --show-progress --progress=dot:mega --timeout=30 --tries=4 -O /usr/local/bin/cloudflared \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    || { echo "khong tai duoc cloudflared ve /usr/local/bin/cloudflared" >&2; exit 1; }
fi
chmod +x /usr/local/bin/cloudflared
# File tai do/ken ma con +x thi "cloudflared tunnel" chet im trong log cua tunnel; --version loc ra ngay.
/usr/local/bin/cloudflared --version
HLS_URL="$(tunnel "$PORT_MTX_HLS" "$LOG_DIR/cf-hls.log")"
echo "HLS public: $HLS_URL"

step "8/8 AI service (FastAPI $PORT_AI)"
daemon "$LOG_DIR/ai.log" "$AI_ROOT" env \
    AI_AVATAR_SERVER="http://127.0.0.1:$PORT_LT" \
    AI_AVATAR_ID="$AVATAR_ID" \
    AI_MEDIA_URL="$HLS_URL/$HLS_PATH/index.m3u8" \
    AI_ALLOWED_ORIGIN="$FE_ORIGIN" \
    python run_ai_server.py
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
