FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    git \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-ai.txt .
RUN pip install --no-cache-dir -r requirements-ai.txt

# LiveTalking engine is not committed (941MB weights). Clone at build time.
ARG LIVETALKING_REF=main
RUN git clone --depth 1 --branch ${LIVETALKING_REF} \
        https://github.com/lipku/LiveTalking.git vendored/LiveTalking \
    && pip install --no-cache-dir -r vendored/LiveTalking/requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY assets/ ./assets/
COPY run_ai_server.py entrypoint.sh ./

RUN chmod +x entrypoint.sh scripts/bootstrap_weights.sh \
    && mkdir -p data/avatars models

EXPOSE 8010 8020

ENTRYPOINT ["./entrypoint.sh"]
