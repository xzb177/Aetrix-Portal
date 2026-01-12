"""
RoyalBot 用户端后端服务启动脚本
"""
import sys
import os

# 添加当前项目路径（必须放在主项目路径之前）
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 添加主项目路径（用于访问主项目的数据库）
main_project = "/root/royalbot"
if main_project not in sys.path:
    sys.path.append(main_project)

import uvicorn

# 直接导入 app 模块而不是使用字符串
from main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )
