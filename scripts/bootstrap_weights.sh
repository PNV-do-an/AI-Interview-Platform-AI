#!/bin/bash
# Bootstrap script: download wav2lip weights và avatar models
# Chạy BEFORE build docker image

set -e

WEIGHTS_URL="https://huggingface.co/shibing624/ai-avatar-wav2lip/resolve/main/wav2lip.pth"
MODELS_DIR="/app/vendored/LiveTalking/models"

echo "Downloading wav2lip.pth..."
wget "$WEIGHTS_URL" -O "$MODELS_DIR/wav2lip.pth"

# Check if we have avatar models already (vn_interviewer_v1)
if [ ! -d "/app/data/avatars/vn_interviewer_v1" ]; then
    echo "Creating vn_interviewer_v1 avatar..."
    mkdir -p "/app/data/avatars/vn_interviewer_v1/full_imgs"
    # Copy placeholder images (you'll need real avatar frames)
    cp /app/assets/vn_interviewer_src.png "/app/data/avatars/vn_interviewer_v1/" 2>/dev/null || true
fi

echo "Weights downloaded successfully!"
