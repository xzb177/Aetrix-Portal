"""RoyalBot 统一后端启动器

一体化启动：门户 API + 自建 Emby 服务器（单进程单端口）

用法:
    python serve.py                     # 默认 0.0.0.0:8000
    PORT=9000 python serve.py           # 通过环境变量指定端口
"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "backend.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info"),
        # 单进程：转码进程管理与内存会话在同一进程内闭环
        workers=1,
    )
