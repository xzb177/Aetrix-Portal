"""
MoviePilot 下载订阅 API
支持自动订阅电影和电视剧
配置优先从数据库读取，回退到环境变量
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.orm import Session

from admin_database_user import get_user_db, SystemConfig
from admin_utils.auth import get_current_admin
from services import test_moviepilot, add_subscribe, get_subscribes


router = APIRouter(tags=["下载管理"])


# ==================== 辅助函数 ====================

def get_config_from_db(db: Session, key: str, default: str = "") -> str:
    """从数据库获取配置，回退到环境变量"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if config and config.value:
        return config.value
    # 回退到环境变量
    import os
    env_map = {
        "moviepilot_url": ("MOVIEPILOT_URL", "http://localhost:3000"),
        "moviepilot_api_token": ("MOVIEPILOT_API_TOKEN", "moviepilot"),
    }
    env_key, fallback = env_map.get(key, (key.upper(), default))
    return os.getenv(env_key, fallback)


def get_moviepilot_config() -> dict:
    """获取 MoviePilot 配置"""
    from admin_database_user import UserSessionLocal
    db = UserSessionLocal()
    try:
        return {
            "url": get_config_from_db(db, "moviepilot_url", "http://localhost:3000"),
            "api_token": get_config_from_db(db, "moviepilot_api_token", "moviepilot"),
        }
    finally:
        db.close()


# ==================== 请求/响应模型 ====================

class MoviePilotConfig(BaseModel):
    """MoviePilot 配置"""
    url: str = Field(..., description="MoviePilot 地址，如 http://localhost:3000")
    api_token: str = Field(..., description="API Token")


class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    url: str
    api_token: str


class AddSubscribeRequest(BaseModel):
    """添加订阅请求"""
    moviepilot: MoviePilotConfig
    name: str = Field(..., description="媒体名称")
    year: Optional[str] = Field(None, description="年份")
    type: str = Field("movie", description="类型: movie 或 tv")
    tmdb_id: Optional[str] = Field(None, description="TMDB ID")
    season: Optional[int] = Field(None, description="季数（电视剧专用）")
    note: Optional[str] = Field(None, description="备注")


class SubscribeInfo(BaseModel):
    """订阅信息"""
    id: str
    name: str
    type: str
    year: Optional[str]
    status: str
    note: Optional[str]


# ==================== API 端点 ====================

@router.post("/test")
async def test_moviepilot_connection(
    request: TestConnectionRequest,
    admin = Depends(get_current_admin)
):
    """测试 MoviePilot 连接"""
    result = await test_moviepilot(request.url, request.api_token)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "连接失败")
        )

    return {"message": "连接成功", "data": result.get("data")}


@router.post("/subscribe")
async def create_subscribe(
    request: AddSubscribeRequest,
    admin = Depends(get_current_admin)
):
    """添加订阅"""
    result = await add_subscribe(
        url=request.moviepilot.url,
        api_token=request.moviepilot.api_token,
        name=request.name,
        year=request.year,
        media_type=request.type,
        tmdb_id=request.tmdb_id,
        season=request.season,
        note=request.note
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "添加订阅失败")
        )

    return {
        "message": "订阅已添加",
        "data": result.get("data")
    }


@router.get("/subscribes")
async def list_subscribes(
    url: Optional[str] = None,
    api_token: Optional[str] = None,
    admin = Depends(get_current_admin)
):
    """获取订阅列表"""
    config = get_moviepilot_config()

    mp_url = url or config["url"]
    token = api_token or config["api_token"]

    result = await get_subscribes(mp_url, token)

    if not result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("error", "获取失败")
        )

    return result


@router.get("/config")
async def get_config(admin = Depends(get_current_admin)):
    """获取当前配置（脱敏）"""
    config = get_moviepilot_config()
    return {
        "url": config["url"],
        "api_token": "***" if config["api_token"] else "",
        "has_config": bool(config["api_token"])
    }
