"""Aetrix 授权管理 API（v2.50.0）

用户购买授权后，管理员（或支付回调）调这里给他的 GitHub 账号发放
GHCR 私有镜像的读权限；到期后由 license_worker 自动回收。

单独成文件：授权发放涉及外部 GitHub API 调用，逻辑集中在这里维护。
鉴权口径与其它 admin router 一致（get_current_admin）。
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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


@router.post("/grant", response_model=LicenseOut)
def grant_license(
    req: GrantRequest,
    current_admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """发放授权：创建记录 + 调 GitHub API 加读权限

    幂等：如果该用户对该包已有 active 授权，直接返回已有记录，
    不会重复调 GitHub API（并发发放不重复）。
    """
    username = req.github_username.strip()
    package = req.package_name.strip()

    # 幂等：已有 active 的直接返回
    existing = (
        db.query(models.License)
        .filter(
            models.License.github_username == username,
            models.License.package_name == package,
            models.License.status == "active",
        )
        .first()
    )
    if existing:
        logger.info("授权已存在，幂等返回：%s -> %s", username, package)
        return existing

    token = _get_token_or_400(db)

    # 先调 GitHub API，成功了再写库（API 失败不留脏记录）
    try:
        license_github.grant_package_access(username, package, token)
    except license_github.GitHubPackageError as e:
        logger.warning("GitHub 授权失败：%s -> %s：%s", username, package, e)
        raise HTTPException(status_code=502, detail=f"GitHub API 调用失败：{e}")

    now = datetime.now()
    lic = models.License(
        github_username=username,
        package_name=package,
        granted_at=now,
        expires_at=now + timedelta(days=req.days),
        status="active",
    )
    db.add(lic)
    db.commit()
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
        logger.warning(
            "GitHub 回收失败：%s -> %s：%s", lic.github_username, lic.package_name, e
        )
        raise HTTPException(status_code=502, detail=f"GitHub API 调用失败：{e}")

    lic.status = "revoked"
    lic.updated_at = datetime.now()
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
