# Single container: the static Next.js export is served by the FastAPI backend on one port.
#   docker build -t kinesight .
#   docker run -p 7860:7860 -e META_API_KEY=... kinesight
# Hosts that assign a port through $PORT (Render, Hugging Face Spaces) run this file as-is.

FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV STATIC_EXPORT=1 NEXT_PUBLIC_API_BASE="" NEXT_TELEMETRY_DISABLED=1
RUN npx next build
WORKDIR /src/decoder
COPY backend/sam_decoder/package.json backend/sam_decoder/package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.13-slim-bookworm
# Check-Date=false tolerates mirror Release files stamped ahead of the builder's clock.
RUN apt-get -o Acquire::Check-Date=false update     && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt backend/
RUN pip install --no-cache-dir --user -r backend/requirements.txt
COPY --chown=user backend/ backend/
COPY --chown=user --from=web /src/decoder/node_modules backend/sam_decoder/node_modules
COPY --chown=user --from=web /src/frontend/out frontend/out

# Guards for a public deployment that spends the owner's API credit (0 = unlimited).
ENV DAILY_VIDEO_JOBS=10 DAILY_RULE_JOBS=40 DAILY_COMPILES=40 \
    MAX_VIDEO_SEC=60 MAX_UPLOAD_MB=200 MAX_CONCURRENT_JOBS=2

WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
