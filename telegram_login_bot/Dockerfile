FROM python:3.12-slim

LABEL maintainer="RoyalBot Portal"
LABEL description="Telegram Login Bot for RoyalBot Portal"

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY main.py .

# 创建非 root 用户
RUN useradd -m -u 1000 botuser && \
    chown -R botuser:botuser /app
USER botuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# 启动 Bot
CMD ["python", "main.py"]
