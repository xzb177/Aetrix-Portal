"""
MoviePilot API 集成服务
支持订阅管理
"""
import httpx
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class MediaType(str, Enum):
    """媒体类型"""
    MOVIE = "movie"
    TV = "tv"


class SubscribeResult(dict):
    """订阅结果"""
    def __init__(self, success: bool, data: Optional[Dict] = None, error: Optional[str] = None):
        super().__init__({
            "success": success,
            "data": data or {},
            "error": error
        })
        self.success = success
        self.data = data or {}
        self.error = error


class MoviePilotClient:
    """MoviePilot 客户端"""

    def __init__(self, url: str, api_token: str):
        self.url = url.rstrip('/')
        self.api_token = api_token
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.api_token}"},
            timeout=30.0
        )
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.aclose()

    async def test_connection(self) -> SubscribeResult:
        """测试连接"""
        try:
            async with self:
                response = await self.client.get("/api/v1/system/progress")
                if response.status_code == 200:
                    return SubscribeResult(success=True, data={"version": "connected"})
                return SubscribeResult(success=False, error=f"HTTP {response.status_code}")
        except Exception as e:
            return SubscribeResult(success=False, error=str(e))

    async def add_subscribe(
        self,
        name: str,
        year: Optional[str] = None,
        media_type: MediaType = MediaType.MOVIE,
        tmdb_id: Optional[str] = None,
        season: Optional[int] = None,
        note: Optional[str] = None
    ) -> SubscribeResult:
        """
        添加订阅

        Args:
            name: 媒体名称
            year: 年份
            media_type: 媒体类型 (movie/tv)
            tmdb_id: TMDB ID
            season: 季数 (电视剧专用)
            note: 备注

        Returns:
            SubscribeResult
        """
        try:
            async with self:
                payload = {
                    "name": name,
                    "type": media_type.value,
                }

                if year:
                    payload["year"] = year
                if tmdb_id:
                    payload["tmdbid"] = tmdb_id
                if season:
                    payload["season"] = season
                if note:
                    payload["note"] = note

                response = await self.client.post("/api/v1/subscribe/", json=payload)

                if response.status_code in (200, 201):
                    data = response.json()
                    return SubscribeResult(success=True, data=data)
                else:
                    return SubscribeResult(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}"
                    )
        except httpx.ConnectError:
            return SubscribeResult(success=False, error="无法连接到 MoviePilot")
        except httpx.TimeoutException:
            return SubscribeResult(success=False, error="连接超时")
        except Exception as e:
            return SubscribeResult(success=False, error=str(e))

    async def get_subscribes(self) -> SubscribeResult:
        """获取所有订阅"""
        try:
            async with self:
                response = await self.client.get(
                    "/api/v1/subscribe/",
                    params={"token": self.api_token}
                )

                if response.status_code == 200:
                    data = response.json()
                    return SubscribeResult(success=True, data=data)
                else:
                    return SubscribeResult(
                        success=False,
                        error=f"HTTP {response.status_code}: {response.text}"
                    )
        except Exception as e:
            return SubscribeResult(success=False, error=str(e))

    async def get_subscribe_status(self, subscribe_id: str) -> SubscribeResult:
        """获取订阅状态"""
        try:
            async with self:
                response = await self.client.get(f"/api/v1/subscribe/{subscribe_id}")

                if response.status_code == 200:
                    data = response.json()
                    return SubscribeResult(success=True, data=data)
                else:
                    return SubscribeResult(
                        success=False,
                        error=f"HTTP {response.status_code}"
                    )
        except Exception as e:
            return SubscribeResult(success=False, error=str(e))


# ==================== 便捷函数 ====================

async def test_moviepilot(url: str, api_token: str) -> Dict:
    """测试 MoviePilot 连接"""
    async with MoviePilotClient(url, api_token) as client:
        result = await client.test_connection()
        return dict(result)


async def add_subscribe(
    url: str,
    api_token: str,
    name: str,
    year: Optional[str] = None,
    media_type: str = "movie",
    tmdb_id: Optional[str] = None,
    season: Optional[int] = None,
    note: Optional[str] = None
) -> Dict:
    """添加订阅"""
    async with MoviePilotClient(url, api_token) as client:
        media_type_enum = MediaType.TV if media_type == "tv" else MediaType.MOVIE
        result = await client.add_subscribe(
            name=name,
            year=year,
            media_type=media_type_enum,
            tmdb_id=tmdb_id,
            season=season,
            note=note
        )
        return dict(result)


async def get_subscribes(url: str, api_token: str) -> Dict:
    """获取订阅列表"""
    async with MoviePilotClient(url, api_token) as client:
        result = await client.get_subscribes()
        return dict(result)
