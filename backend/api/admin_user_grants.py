"""
管理后台 API · 用户授权资源卡片（Phase 4）

``GET /api/admin/user-grants/{user_id}``：一个服一张卡片，回答「这个用户被授权了什么」——
每个服提供什么资源（媒体库 / 条目 / 挂载 / 出流节点）、他在该服被授权到什么程度
（订阅生效中 / 即将到期 / 已到期 / 未授权 / 积分解锁 / 公益服免费开放）、
以及这份授权**能做什么**（能否播放、能否查看 Emby 账号与线路、能否下载）。

**纯只读**：卡片组装在 ``backend/user_grants.py``（那里写清了口径与三条易错点），
本模块只做鉴权、查用户、转交。发放 / 撤销授权仍在用户详情与服管理里做。

鉴权用 ``get_current_admin``（``is_staff`` + ``backend/admin_roles.py`` 角色判定），
与其它 ``/api/admin/*`` 端点一致。**不用** ``require_staff``：那个依赖挂在
``admin_emby_router`` 上，还额外要求「自建 Emby 后端可用」——本端点读的是订阅与服
的资源统计，后端停用时也必须能看，所以不走它。
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from backend import models, user_grants
from backend.api.admin_core import admin_router, get_current_admin
from backend.database import get_db


@admin_router.get("/user-grants/{user_id}")
def get_user_grants(
    user_id: int,
    current_admin: models.WebUser = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """某个用户的授权资源卡片（一个服一张）+ 顶部汇总"""
    user = db.query(models.WebUser).filter(models.WebUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user_grants.cards(db, user)
