# syntax=docker/dockerfile:1

FROM node:22-alpine AS user-build
WORKDIR /src/user_frontend
COPY user_frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY user_frontend/ ./
RUN npm run build-only

FROM node:22-alpine AS admin-build
WORKDIR /src/admin_frontend
COPY admin_frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY admin_frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
# 版本号单一来源：显式先放一份，避免将来 .dockerignore 调整时漏掉它
COPY VERSION /app/VERSION
COPY . /app
COPY --from=user-build /src/user_frontend/dist /app/user_frontend/dist
COPY --from=admin-build /src/admin_frontend/dist /app/admin_frontend/dist
ENV FRONTEND_DIST=/app/user_frontend/dist \
    ADMIN_DIST=/app/admin_frontend/dist \
    HOST=0.0.0.0 \
    PORT=8000 \
    ENABLE_EMBY_GATEWAY=true \
    EMBY_FFMPEG_PATH=ffmpeg
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "serve.py"]
