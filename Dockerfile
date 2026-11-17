FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    HF_HOME=/tmp/huggingface \
    NUMBA_CACHE_DIR=/tmp/numba \
    SSL_CERT_FILE=/app/src/aetherwaves/nasa_ca_bundle.pem \
    REQUESTS_CA_BUNDLE=/app/src/aetherwaves/nasa_ca_bundle.pem

# Install system dependencies: ca-certificates, ffmpeg, fluidsynth, FluidR3_GM, OpenCV libs, espeak-ng, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    fluidsynth \
    fluid-soundfont-gm \
    libgl1 \
    libglib2.0-0 \
    espeak-ng \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Link FluidR3_GM soundfont so repository paths resolve
RUN mkdir -p soundfonts && ln -s /usr/share/sounds/sf2/FluidR3_GM.sf2 soundfonts/FluidR3_GM.sf2

# Pre-download Kokoro-82M ONNX model and voices into /app/models/kokoro/
RUN mkdir -p /app/models/kokoro && \
    curl -L -s -o /app/models/kokoro/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx && \
    curl -L -s -o /app/models/kokoro/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

# Pre-download Whisper base.en model into /app/models/whisper/base.en/
RUN mkdir -p /app/models/whisper/base.en && \
    curl -L -s -o /app/models/whisper/base.en/config.json https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/config.json && \
    curl -L -s -o /app/models/whisper/base.en/model.bin https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/model.bin && \
    curl -L -s -o /app/models/whisper/base.en/tokenizer.json https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/tokenizer.json && \
    curl -L -s -o /app/models/whisper/base.en/vocabulary.txt https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/vocabulary.txt

# Pre-download OSCAR global 505MB NetCDF dataset from GitHub Release data-v1
RUN mkdir -p /app/data && \
    curl -L -s -o /app/data/oscar_global.nc https://github.com/nullkai-empt/thesound.earth/releases/download/data-v1/oscar_global.nc

# Copy package metadata and install dependencies
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# Copy application code
COPY . .

# Red Hat OpenShift restricted-v2 security context compliance (arbitrary UID, GID 0)
RUN mkdir -p /tmp/huggingface /tmp/numba && \
    chgrp -R 0 /app /tmp && \
    chmod -R g=u /app /tmp

USER 10001

EXPOSE 8000

CMD ["uvicorn", "aetherwaves.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
