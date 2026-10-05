"""授权过期回收 daemon（v2.50.0）

每小时检查一次：把已过期（expires_at < now）但状态还是 active 的授权
自动 revoke——调 GitHub API 回收权限 + 更新记录状态为 expired。

启动方式：在 backend/worker.py 里加一段（参考 auto_scan / db_backup）：
    from backend.emby_server import license_worker
    license_worker.start_license_reclaimer()

daemon 线程，随进程退出；同一进程只启动一次。
"""
import logging
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

# 每小时检查一次
CHECK_INTERVAL_SEC = 3600

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()


def _reclaim_expired_once() -> int:
    """回收一轮过期的授权，返回回收数量"""
    from backend.database import SessionLocal
    from backend.emby_server import license_github, models

    db = SessionLocal()
    try:
        now = datetime.now()
        expired = (
            db.query(models.License)
            .filter(
                models.License.status == "active",
                models.License.expires_at.isnot(None),
                models.License.expires_at < now,
            )
            .all()
        )
        if not expired:
            return 0

        try:
            token = license_github.get_token_from_db(db)
        except license_github.GitHubPackageError as e:
            logger.warning("授权回收跳过：%s", e)
            return 0

        count = 0
        for lic in expired:
            try:
                license_github.revoke_package_access(
                    lic.github_username, lic.package_name, token
                )
                lic.status = "expired"
                lic.updated_at = now
                db.commit()
                count += 1
                logger.info(
                    "授权到期自动回收：%s -/-> %s",
                    lic.github_username, lic.package_name,
                )
            except license_github.GitHubPackageError as e:
                # 单个失败不影响其它，下一轮再试
                db.rollback()
                logger.warning(
                    "授权回收失败（下一轮重试）：%s -> %s：%s",
                    lic.github_username, lic.package_name, e,
                )
            except Exception as e:  # noqa: BLE001 — 同上
                db.rollback()
                logger.warning("授权回收异常：%s", e)
        return count
    finally:
        db.close()


def _loop() -> None:
    while True:
        threading.Event().wait(CHECK_INTERVAL_SEC)
        try:
            n = _reclaim_expired_once()
            if n:
                logger.info("授权回收 daemon：一轮回收 %d 条过期授权", n)
        except Exception as e:  # noqa: BLE001 — daemon 不能死
            logger.warning("授权回收 daemon 异常：%s", e)


def start_license_reclaimer() -> bool:
    """启动授权回收线程（同一进程只启动一次；daemon，随进程退出）"""
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        _SCHEDULER_STARTED = True

    threading.Thread(target=_loop, daemon=True, name="license-reclaimer").start()
    logger.info("授权过期回收已启动（每 %d 秒检查一次）", CHECK_INTERVAL_SEC)
    return True
