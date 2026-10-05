"""授权过期回收 daemon（v2.50.0）

每小时检查一次：把已过期（expires_at < now）但状态还是 active 的授权
自动 revoke——调 GitHub API 回收权限 + 更新记录状态为 expired。

启动方式：在 backend/worker.py 里加一段（参考 auto_scan / db_backup）：
    from backend.emby_server import license_worker
    license_worker.start_license_reclaimer()

daemon 线程，随进程退出；同一进程只启动一次。

第二遍打磨（审查意见落实）：
- 时间统一用 naive UTC（license_github._utcnow），不混本地时区；
- 限流熔断：收到 GitHubRateLimitError 立刻停下本轮，剩下的下一轮再试，
  而不是把每个条目都试一遍烧光配额；
- 部分失败隔离：单个 revoke 失败只回滚自己，不影响其它条目，
  且回收循环本身绝不抛异常中断 daemon。
"""
import logging
import threading

logger = logging.getLogger(__name__)

# 每小时检查一次
CHECK_INTERVAL_SEC = 3600

_SCHEDULER_STARTED = False
_SCHEDULER_LOCK = threading.Lock()


def _reclaim_expired_once() -> int:
    """回收一轮过期的授权，返回成功回收数量"""
    from backend.database import SessionLocal
    from backend.emby_server import license_github, models

    db = SessionLocal()
    try:
        now = license_github.utcnow()
        expired = (
            db.query(models.License)
            .filter(
                models.License.status == "active",
                models.License.expires_at.isnot(None),
                models.License.expires_at < now,
            )
            .order_by(models.License.expires_at.asc())
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
            # 先取出来，后面 rollback 不影响日志打印
            username = lic.github_username
            package = lic.package_name
            lic_id = lic.id
            try:
                license_github.revoke_package_access(username, package, token)
            except license_github.GitHubRateLimitError as e:
                # 限流熔断：停下本轮，剩下的下一轮再试
                logger.warning(
                    "GitHub 限流，授权回收本轮中止（已回收 %d 条，剩余下轮）：%s",
                    count, e,
                )
                break
            except license_github.GitHubPackageError as e:
                # 单个失败不影响其它，下一轮再试
                db.rollback()
                logger.warning(
                    "授权回收失败（下一轮重试）：%s -> %s：%s",
                    username, package, e,
                )
                continue
            except Exception as e:  # noqa: BLE001 — 同上
                db.rollback()
                logger.warning(
                    "授权回收异常（id=%s）：%s", lic_id, e,
                )
                continue
            try:
                lic.status = "expired"
                lic.updated_at = license_github.utcnow()
                db.commit()
                count += 1
                logger.info("授权到期自动回收：%s -/-> %s", username, package)
            except Exception as e:  # noqa: BLE001 — 写库失败不影响其它
                db.rollback()
                logger.warning("授权状态写库失败（id=%s）：%s", lic_id, e)
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
