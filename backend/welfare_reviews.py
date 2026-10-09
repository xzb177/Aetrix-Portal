# -*- coding: utf-8 -*-
"""影评业务逻辑（公益服模块3-娱乐板块）

手动编写（OpenRouter 免费模型 429 限流，按 backend/points.py 模式手写）。

规则：
- 发表影评奖励积分（调用 points.award_chat_points，复用发言奖励额度）
- rating 1-5
- 点赞：likes +1（SQL 级自增，防并发丢更新）
"""

from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger(__name__)


def create_review(
    db: Session,
    user: models.WebUser,
    item_guid: str,
    rating: int,
    content: str,
) -> models.Review:
    """发表影评"""
    item_guid = (item_guid or "").strip()
    content = (content or "").strip()
    if not item_guid:
        raise ValueError("item_guid 不能为空")
    if not content:
        raise ValueError("影评内容不能为空")
    if len(content) > 2000:
        raise ValueError("影评内容不能超过2000字")
    if rating not in (1, 2, 3, 4, 5):
        raise ValueError("评分只能是 1-5")

    review = models.Review(
        user_id=user.id,
        item_guid=item_guid,
        rating=rating,
        content=content,
        likes=0,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    # 发表影评奖励积分（复用发言奖励的日额度）
    try:
        from backend import points as points_mod
        points_mod.award_chat_points(db, user.id)
    except Exception as e:
        logger.debug("影评积分奖励失败: %s", e)

    logger.info("影评发表: user=%s guid=%s rating=%s", user.id, item_guid, rating)
    return review


def list_reviews(
    db: Session,
    item_guid: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """某影片的影评列表（按点赞倒序）"""
    q = db.query(models.Review).filter(
        models.Review.item_guid == item_guid
    ).order_by(models.Review.likes.desc(), models.Review.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()

    user_ids = {r.user_id for r in items}
    users = {u.id: u.username for u in db.query(models.WebUser).filter(
        models.WebUser.id.in_(user_ids)).all()} if user_ids else {}

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": users.get(r.user_id, "未知"),
                "item_guid": r.item_guid,
                "rating": r.rating,
                "content": r.content,
                "likes": r.likes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
    }


def like_review(db: Session, review_id: int) -> dict:
    """点赞（SQL 级自增）"""
    review = db.query(models.Review).filter(
        models.Review.id == review_id).first()
    if review is None:
        raise ValueError("影评不存在")

    db.query(models.Review).filter(models.Review.id == review_id).update(
        {models.Review.likes: func.coalesce(models.Review.likes, 0) + 1},
        synchronize_session="fetch",
    )
    db.commit()

    likes = db.query(models.Review.likes).filter(
        models.Review.id == review_id).scalar() or 0
    return {"id": review_id, "likes": int(likes)}


def my_reviews(
    db: Session,
    user: models.WebUser,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """我的影评"""
    q = db.query(models.Review).filter(
        models.Review.user_id == user.id
    ).order_by(models.Review.id.desc())
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "item_guid": r.item_guid,
                "rating": r.rating,
                "content": r.content,
                "likes": r.likes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
    }
