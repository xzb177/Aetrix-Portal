"""Aetrix 授权管理 API（v2.50.0）

用户购买授权后，管理员（或支付回调）调这里给他的 GitHub 账号发放
GHCR 私有镜像的读权限；到期后由 license_worker 自动回收。

单独成文件：授权发放涉及外部 GitHub API 调用，逻辑集中在这里维护。
鉴权口径与其它 admin router 一致（get_current_admin）。

第二遍打磨（审查意见落实）：
- 并发安全：(github_username, package_name, status) 有 DB 唯一约束，
  两管理员同时发放时只有一个能写入，另一个走 IntegrityError 分支
  幂等返回已有记录，不会建出两条；
- 时间统一用 naive UTC（license_github._utcnow），不混本地时区；
- 限流单独报 503（可重试），其它 GitHub 错误报 502。
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.admin_core import get_current_admin
from backend.database import get_db
from backend.emby_server import license_github, models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/licenses", tags=["管理后台-授权发放"])


class GrantRequest(BaseModel):
    """发放授权请求"""
    github_username: str = Field(..., min_length=1, max_length=100,
                                description="被授权人的 GitHub 用户名")
    package_name: str = Field(..., min_length=1, max_length=200,
                              description="包名，如 aetrix-web")
    days: int = Field(default=365, ge=1, le=3650,
                      description="有效天数，默认 365")


class RevokeRequest(BaseModel):
    """回收授权请求"""
    license_id: int = Field(..., description="授权记录 id")


class LicenseOut(BaseModel):
    """授权记录输出"""
    id: int
    github_username: str
    package_name: str
    granted_at: Optional[datetime]
    expires_at: Optional[datetime]
    status: str

    class Config:
        from_attributes = True


def _get_token_or_400(db: Session) -> str:
    """读 GitHub token，缺失时报 400（给管理员看的清晰提示）"""
    try:
        return license_github.get_token_from_db(db)
    except license_github.GitHubPackageError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _find_active(db: Session, username: str, package: str):
    """查该用户对该包的 active 授权（幂等判断用）"""
    return (
        db.query(models.License)
        .filter(
            models.License.github_username == username,
            models.License.package_name == package,
            models.License.status == "active",
        )
        .first()
    )


def _github_error_to_http(e: license_github.GitHubPackageError,
                          username: str, package: str) -> HTTPException:
    """GitHub 错误转 HTTP 状态码：限流 503（前端可退避重试），其它 502"""
    if isinstance(e, license_github.GitHubRateLimitError):
        logger.warning("GitHub 限流，发放暂缓：%s -> %s：%s", username, package, e)
        return HTTPException(status_code=503, detail=f"GitHub API 限流，请稍后重试：{e}")
    logger.warning("GitHub 授权失败：%s -> %s：%s", username, package, e)
    return HTTPException(status_code=502, detail=f"GitHub API 调用失败：{e}")


@router.post("/grant", response_model=LicenseOut)
def grant_license(
    req: GrantRequest,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """发放授权：创建记录 + 调 GitHub API 加读权限

    幂等（两层）：
    1. 先查后写：已有 active 的直接返回，不调 GitHub API；
    2. DB 唯一约束兜底：两请求同时通过第 1 步时，只有一个能写入，
       另一个触发 IntegrityError，回滚后返回胜出的那条记录。

    顺序是「先调 GitHub API，成功再写库」：API 失败不留脏记录；
    若 API 成功但写库失败，重试时 GitHub PUT 是幂等的，不会重复授权。
    """
    username = req.github_username.strip()
    package = req.package_name.strip()

    # 第 1 层幂等：已有 active 的直接返回
    existing = _find_active(db, username, package)
    if existing:
        logger.info("授权已存在，幂等返回：%s -> %s", username, package)
        return existing

    token = _get_token_or_400(db)

    # 先调 GitHub API，成功了再写库（API 失败不留脏记录）
    try:
        license_github.grant_package_access(username, package, token)
    except license_github.GitHubPackageError as e:
        raise _github_error_to_http(e, username, package)

    now = license_github.utcnow()
    lic = models.License(
        github_username=username,
        package_name=package,
        granted_at=now,
        expires_at=now + timedelta(days=req.days),
        status="active",
    )
    db.add(lic)
    try:
        db.commit()
    except IntegrityError:
        # 第 2 层幂等：并发下另一请求已先写入，回滚后返回那条记录
        db.rollback()
        winner = _find_active(db, username, package)
        if winner is not None:
            logger.info(
                "并发发放冲突，幂等返回胜出记录：%s -> %s (id=%s)",
                username, package, winner.id,
            )
            return winner
        # 极端情况：约束冲突但查不到 active（理论上不应发生），如实报错
        logger.error("发放授权唯一约束冲突但无 active 记录：%s -> %s", username, package)
        raise HTTPException(status_code=409, detail="授权记录冲突，请重试")
    db.refresh(lic)
    logger.info("授权发放成功：%s -> %s，有效期 %d 天", username, package, req.days)
    return lic


@router.post("/revoke")
def revoke_license(
    req: RevokeRequest,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """回收授权：调 GitHub API 删权限 + 更新记录状态为 revoked"""
    lic = db.query(models.License).filter(models.License.id == req.license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    if lic.status != "active":
        return {"ok": True, "message": f"该授权已是 {lic.status} 状态，无需回收"}

    token = _get_token_or_400(db)

    try:
        license_github.revoke_package_access(
            lic.github_username, lic.package_name, token
        )
    except license_github.GitHubPackageError as e:
        raise _github_error_to_http(e, lic.github_username, lic.package_name)

    lic.status = "revoked"
    lic.updated_at = license_github.utcnow()
    db.commit()
    logger.info("授权已回收：%s -/-> %s", lic.github_username, lic.package_name)
    return {"ok": True, "message": "已回收"}


@router.get("", response_model=List[LicenseOut])
def list_licenses(
    status: Optional[str] = None,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """授权列表，支持按 status 过滤（active/expired/revoked）"""
    q = db.query(models.License).order_by(models.License.id.desc())
    if status:
        if status not in ("active", "expired", "revoked"):
            raise HTTPException(status_code=400, detail="status 非法")
        q = q.filter(models.License.status == status)
    return q.limit(500).all()
