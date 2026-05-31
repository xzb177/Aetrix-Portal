"""
观影旅程画像服务
聚合用户的观看数据，生成观影偏好画像
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from database.models import WebUser, UserEmbyAccount, EmbyServer
from utils.emby_client import EmbyClient

logger = logging.getLogger(__name__)


class ViewingProfileService:
    """观影画像分析"""

    @staticmethod
    def generate_profile(user_id: int, db: Session) -> Dict[str, Any]:
        """
        生成用户的观影画像

        从 Emby 服务器拉取播放数据，聚合分析后返回
        """
        try:
            # 获取用户的 Emby 账号
            accounts = db.query(UserEmbyAccount).filter(
                UserEmbyAccount.user_id == user_id,
                UserEmbyAccount.is_active == True
            ).all()

            if not accounts:
                return {"error": "无活跃 Emby 账号"}

            all_items = []
            for account in accounts:
                server = db.query(EmbyServer).filter(
                    EmbyServer.id == account.server_id
                ).first()
                if not server or not server.is_active:
                    continue

                client = EmbyClient(server.url, server.api_key)
                # 获取用户最近播放记录
                items = client.get_user_items(
                    account.emby_user_id,
                    sort_by="DatePlayed",
                    limit=200
                )
                if items:
                    all_items.extend(items)

            if not all_items:
                return {"error": "无播放记录"}

            # 聚合分析
            return ViewingProfileService._analyze_items(all_items)

        except Exception as e:
            logger.error(f"生成观影画像失败: {e}")
            return {"error": str(e)}

    @staticmethod
    def _analyze_items(items: List[Dict]) -> Dict[str, Any]:
        """分析播放记录，生成画像"""
        genre_counts = {}
        type_counts = {}
        device_counts = {}
        hour_counts = {}
        total_ticks = 0
        drop_count = 0

        for item in items:
            # 类型统计
            genres = item.get("Genres", [])
            for g in genres:
                genre_counts[g] = genre_counts.get(g, 0) + 1

            # 媒体类型
            media_type = item.get("Type", "Unknown")
            type_counts[media_type] = type_counts.get(media_type, 0) + 1

            # 播放时长
            ticks = item.get("UserData", {}).get("PlayCount", 0)
            total_ticks += ticks

            # 弃剧检测（播放进度 < 20% 视为弃剧）
            played_pct = item.get("UserData", {}).get("PlayedPercentage", 100)
            if played_pct < 20 and played_pct > 0:
                drop_count += 1

        # 排序取 Top
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)

        return {
            "total_items": len(items),
            "top_genres": [{"name": g, "count": c} for g, c in top_genres],
            "type_distribution": {t: c for t, c in top_types},
            "drop_off_count": drop_count,
            "drop_off_rate": round(drop_count / max(len(items), 1) * 100, 1),
            "favorite_genres": [g for g, _ in top_genres],
            "generated_at": datetime.now().isoformat()
        }

    @staticmethod
    def get_recommendations(user_id: int, db: Session) -> List[Dict]:
        """基于画像生成推荐"""
        profile = ViewingProfileService.generate_profile(user_id, db)
        if "error" in profile:
            return []

        # 基于 Top 类型推荐
        recommendations = []
        for genre in profile.get("favorite_genres", [])[:3]:
            recommendations.append({
                "type": "genre_recommendation",
                "genre": genre,
                "reason": f"你经常观看{genre}类内容",
                "priority": "high"
            })

        # 弃剧率高时推荐
        if profile.get("drop_off_rate", 0) > 30:
            recommendations.append({
                "type": "suggestion",
                "message": "你弃剧率较高，试试求片中心推荐的热门内容",
                "priority": "medium"
            })

        return recommendations
