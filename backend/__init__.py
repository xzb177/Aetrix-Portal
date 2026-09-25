"""Aetrix Portal backend package bootstrap."""
from pathlib import Path

from dotenv import load_dotenv

# 所有后端模块都可能先于 ``backend.main`` 被 CLI / worker 导入；在包入口统一加载
# 根目录 .env，且不覆盖 systemd / 容器已经注入的环境变量。
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

# 版本号单一来源：根目录 VERSION（别再在这里另写一份）
from backend.version import app_version  # noqa: E402

__version__ = app_version()
