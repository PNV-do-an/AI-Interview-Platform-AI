#!/bin/bash
# Chạy cả hai tiến trình trong một container:
#   :8010 LiveTalking (avatar engine)   :8020 FastAPI (AI service)
set -e

bash scripts/bootstrap_weights.sh || echo "WARN: weights bootstrap failed"

cd vendored/LiveTalking
python /app/scripts/run_server.py \
    --config /app/config/livetalking.yaml \
    --transport webrtc --stun '' --listenport 8010 &
LIVETALKING_PID=$!
cd /app

for i in $(seq 1 60); do
    curl -sf http://127.0.0.1:8010/api/admin/sessions >/dev/null 2>&1 && break
    sleep 1
done

python run_ai_server.py &
AI_PID=$!

trap 'kill $LIVETALKING_PID $AI_PID 2>/dev/null' TERM INT
wait -n $LIVETALKING_PID $AI_PID
