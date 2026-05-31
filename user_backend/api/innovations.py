"""
创新功能 API 端点
登录自诊断 / 观影画像 / 家庭席位 / 阶梯邀请 / 智能续费 / 流失挽留 / 异常雷达
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional

from database import get_session
from api.auth import get_current_user
from database.models import WebUser

router = APIRouter(tags=["创新功能"])


# ==================== 登录自诊断 ====================

@router.get("/diagnosis/login")
async def login_diagnosis(
    username: str = Query(..., description="用户名"),
    db: Session = Depends(get_session)
):
    """登录自诊断：检测登录失败原因"""
    from services.login_diagnosis import LoginDiagnosis
    result = LoginDiagnosis.diagnose(username, db)
    return result


@router.get("/diagnosis/servers")
async def server_diagnosis(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """Emby 服务器状态诊断"""
    from services.login_diagnosis import LoginDiagnosis
    return LoginDiagnosis.quick_check(db)


# ==================== 观影旅程画像 ====================

@router.get("/viewing/profile")
async def get_viewing_profile(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """获取当前用户的观影画像"""
    from services.viewing_profile import ViewingProfileService
    return ViewingProfileService.generate_profile(current_user.id, db)


@router.get("/viewing/recommendations")
async def get_recommendations(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """基于观影画像的智能推荐"""
    from services.viewing_profile import ViewingProfileService
    return ViewingProfileService.get_recommendations(current_user.id, db)


# ==================== 家庭席位 ====================

@router.get("/family")
async def get_family_info(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """获取我的家庭组信息"""
    from services.family_service import FamilyService
    return FamilyService.get_family_info(current_user.id, db)


@router.post("/family/create")
async def create_family(
    plan_type: str = "standard",
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """创建家庭组"""
    from services.family_service import FamilyService
    return FamilyService.create_family(current_user.id, plan_type, db)


@router.post("/family/add-member")
async def add_family_member(
    username: str,
    nickname: str = "",
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """添加家庭成员"""
    from services.family_service import FamilyService
    return FamilyService.add_member(current_user.id, username, nickname, db)


@router.post("/family/remove-member")
async def remove_family_member(
    member_id: int,
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """移除家庭成员"""
    from services.family_service import FamilyService
    return FamilyService.remove_member(current_user.id, member_id, db)


# ==================== 阶梯邀请 ====================

@router.get("/invite/tiers")
async def get_invite_tiers(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """获取阶梯邀请进度"""
    from services.tiered_invite import TieredInviteService
    return TieredInviteService.get_progress(current_user.id, db)


@router.post("/invite/check-rewards")
async def check_invite_rewards(
    db: Session = Depends(get_session),
    current_user: WebUser = Depends(get_current_user)
):
    """检查并领取阶梯邀请奖励"""
    from services.tiered_invite import TieredInviteService
    rewards = TieredInviteService.check_and_reward(current_user.id, db)
    return {"rewards": rewards, "count": len(rewards)}


# ==================== 智能续费提醒（管理端） ====================

@router.post("/admin/smart-reminders/run")
async def run_smart_reminders(
    db: Session = Depends(get_session)
):
    """运行智能续费提醒（管理端调用）"""
    from services.smart_reminder import SmartReminderService
    result = SmartReminderService.check_and_remind(db)
    return {"status": "completed", "stats": result}


# ==================== 流失预测（管理端） ====================

@router.get("/admin/churn/scan")
async def scan_churn_risk(
    auto_action: bool = Query(False, description="是否自动执行挽留"),
    db: Session = Depends(get_session)
):
    """扫描流失风险用户"""
    from services.churn_prediction import ChurnPredictionService
    result = ChurnPredictionService.run_churn_scan(db, auto_action)
    return result


@router.get("/admin/churn/user/{user_id}")
async def get_user_churn_risk(
    user_id: int,
    db: Session = Depends(get_session)
):
    """获取单个用户的流失风险评估"""
    from services.churn_prediction import ChurnPredictionService
    return ChurnPredictionService.analyze_user(user_id, db)


# ==================== 异常收入雷达（管理端） ====================

@router.get("/admin/radar/dashboard")
async def get_radar_dashboard(
    db: Session = Depends(get_session)
):
    """获取异常收入雷达仪表盘"""
    from services.revenue_radar import RevenueRadarService
    return RevenueRadarService.get_dashboard(db)


@router.get("/admin/radar/scan")
async def scan_revenue_anomalies(
    days: int = Query(7, description="扫描天数"),
    db: Session = Depends(get_session)
):
    """扫描异常收入行为"""
    from services.revenue_radar import RevenueRadarService
    return RevenueRadarService.scan_anomalies(db, days)
