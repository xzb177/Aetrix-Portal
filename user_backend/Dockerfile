# RoyalBot User Backend Dockerfile
# 多阶段构建以减小镜像大小

# ==================== 阶段1: 构建阶段 ====================
FROM python:3.11-slim AS builder

# 设置工作目录
WORKDIR /build

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖到系统目录（不在使用 --user）
RUN pip install --no-cache-dir -r requirements.txt

# ==================== 阶段2: 运行阶段 ====================
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 创建非 root 用户
RUN groupadd -r royalbot && useradd -r -g royalbot royalbot

# 设置工作目录
WORKDIR /app

# 从构建阶段复制依赖（从 /usr/local 复制）
COPY --from=builder /usr/local /usr/local

# 复制应用代码
COPY . .

# 创建日志目录并设置权限
RUN mkdir -p /app/logs && \
    chown -R royalbot:royalbot /app

# 切换到非 root 用户
USER royalbot

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

# 暴露端口
EXPOSE 8001

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
