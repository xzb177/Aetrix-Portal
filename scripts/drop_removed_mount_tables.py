#!/usr/bin/env python3
"""删除 v2.42.12 精简挂载后遗留的三张表（**必须显式加 --yes**）

背景：面板从「代管 rclone.conf + Google Drive 原生挂载」改成「用户自己粘贴
rclone.conf、只留 115 / rclone / 本地」之后，这三张表再也没有代码读写：

- ``rclone_remotes``      —— 面板从库里生成 rclone.conf（现在由用户粘贴）
- ``service_account_files``—— Google Drive 服务账号 JSON 的元数据
- ``emby_mount_file_ids`` —— Google Drive「相对路径 → file id」播放秒开缓存

**为什么不在启动时自动 DROP**：这三张表里可能有客户还在用的服务账号路径配置。
启动时自动删 = 删掉别人机器上的数据且无法撤销。所以这里只提供一个脚本，
必须显式 ``--yes`` 才会执行，而且先把要删的行数打印出来。

删表**不是升级的前置条件**：ORM 里已经没有了，不删也只是多三张占空间的空表，
功能完全不受影响。确认自己的 rclone.conf 已经粘好、跑通了，再回来清。

用法::

    venv/bin/python scripts/drop_removed_mount_tables.py            # 只看会删什么
    venv/bin/python scripts/drop_removed_mount_tables.py --yes      # 真删
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import inspect, text  # noqa: E402

from backend.database import SessionLocal, engine  # noqa: E402

TABLES = ("rclone_remotes", "service_account_files", "emby_mount_file_ids")


def main(argv: list[str]) -> int:
    confirmed = "--yes" in argv[1:]
    present = [name for name in TABLES if name in inspect(engine).get_table_names()]
    if not present:
        print("没有需要清理的表（已经清过了，或是从头装的）")
        return 0

    session = SessionLocal()
    try:
        print("将要删除以下表：")
        for name in present:
            count = session.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar() or 0
            print(f"  - {name}（{count} 行）")
        if not confirmed:
            print("\n这是预览。确认无误后加 --yes 重新执行。")
            return 1
        for name in present:
            session.execute(text(f"DROP TABLE IF EXISTS {name}"))
        session.commit()
        print(f"\n已删除 {len(present)} 张表。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))