"""rclone remote 管理：从数据库生成 rclone.conf

设计原则：配置数据驱动，不直接写 rclone.conf 文件。
- RcloneRemote 表存所有 remote 配置
- generate_rclone_conf() 从 DB 生成配置文件内容
- write_rclone_conf() 写入到指定路径（默认 ~/.config/rclone/rclone.conf）
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def generate_rclone_conf(db) -> str:
    """从数据库的 rclone_remotes 表生成 rclone.conf 内容"""
    from backend.emby_server import models as em

    remotes = (
        db.query(em.RcloneRemote)
        .filter(em.RcloneRemote.is_enabled == True)  # noqa: E712
        .order_by(em.RcloneRemote.name)
        .all()
    )

    lines = []
    for r in remotes:
        lines.append(f"[{r.name}]")
        lines.append(f"type = {r.remote_type or 'drive'}")

        if r.remote_type == "drive":
            # OAuth 方式
            if r.client_id:
                lines.append(f"client_id = {r.client_id}")
            if r.client_secret:
                lines.append(f"client_secret = {r.client_secret}")
            if r.scope:
                lines.append(f"scope = {r.scope}")
            if r.token_json:
                # token 是 JSON，需要转义换行
                token_escaped = r.token_json.replace("\n", "\\n")
                lines.append(f"token = {token_escaped}")
            # 服务账号方式
            if r.sa_file_id:
                sa = (
                    db.query(em.ServiceAccountFile)
                    .filter(em.ServiceAccountFile.id == r.sa_file_id)
                    .first()
                )
                if sa and sa.stored_path:
                    lines.append(f"service_account_file = {sa.stored_path}")
            if r.team_drive:
                lines.append(f"team_drive = {r.team_drive}")
            if r.chunk_size:
                lines.append(f"chunk_size = {r.chunk_size}")

        lines.append("")  # remote 之间空行

    return "\n".join(lines)


def write_rclone_conf(db, conf_path: Optional[str] = None) -> str:
    """生成并写入 rclone.conf，返回写入路径"""
    if conf_path is None:
        conf_path = os.path.expanduser("~/.config/rclone/rclone.conf")

    content = generate_rclone_conf(db)

    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    # 备份旧配置
    if os.path.exists(conf_path):
        backup = conf_path + ".bak"
        import shutil
        shutil.copy2(conf_path, backup)
        logger.info("rclone.conf 已备份到 %s", backup)

    with open(conf_path, "w") as f:
        f.write(content)

    # 权限 600（可能含 token/secret）
    os.chmod(conf_path, 0o600)
    logger.info("rclone.conf 已从数据库重新生成：%s", conf_path)
    return conf_path


def get_probe_remote(db) -> Optional[str]:
    """获取当前探测用的 remote 名称（is_probe_remote=True 的那个）"""
    from backend.emby_server import models as em

    r = (
        db.query(em.RcloneRemote)
        .filter(
            em.RcloneRemote.is_probe_remote == True,  # noqa: E712
            em.RcloneRemote.is_enabled == True,  # noqa: E712
        )
        .first()
    )
    return r.name if r else None


def set_probe_remote(db, remote_id: int) -> bool:
    """设置探测用 remote（全局唯一）"""
    from backend.emby_server import models as em

    # 先清掉所有
    db.query(em.RcloneRemote).update({em.RcloneRemote.is_probe_remote: False})
    # 设置新的
    r = db.query(em.RcloneRemote).filter(em.RcloneRemote.id == remote_id).first()
    if not r:
        return False
    r.is_probe_remote = True
    db.commit()
    logger.info("探测 remote 已切换到：%s", r.name)
    return True
