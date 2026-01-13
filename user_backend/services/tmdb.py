"""
TMDB API 集成服务
用于搜索影片、获取海报和元数据
"""
import os
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# TMDB API 默认配置
TMDB_DEFAULT_BASE_URL = "https://api.themoviedb.org/3"
TMDB_DEFAULT_IMAGE_BASE_URL = "https://image.tmdb.org/t/p"
TMDB_DEFAULT_LANGUAGE = "zh-CN"

# 配置缓存（避免频繁请求 admin backend）
_tmdb_config_cache = {
    "api_key": "",
    "base_url": TMDB_DEFAULT_BASE_URL,
    "image_base_url": TMDB_DEFAULT_IMAGE_BASE_URL,
    "language": TMDB_DEFAULT_LANGUAGE,
    "cache_time": None
}


def _load_tmdb_config() -> Dict[str, str]:
    """
    从 admin backend 加载 TMDB 配置

    Returns:
        包含 api_key, base_url, image_base_url, language 的字典
    """
    global _tmdb_config_cache

    # 缓存有效期 5 分钟
    if _tmdb_config_cache["cache_time"]:
        cache_age = (datetime.now() - _tmdb_config_cache["cache_time"]).total_seconds()
        if cache_age < 300:  # 5 分钟
            return {
                "api_key": _tmdb_config_cache["api_key"],
                "base_url": _tmdb_config_cache["base_url"],
                "image_base_url": _tmdb_config_cache["image_base_url"],
                "language": _tmdb_config_cache["language"],
            }

    try:
        # 从 admin backend 获取配置
        admin_backend_url = os.getenv("ADMIN_BACKEND_URL", "http://royalbot_admin_backend:8080")
        response = httpx.get(
            f"{admin_backend_url}/api/settings/public/tmdb",
            timeout=5.0
        )
        response.raise_for_status()
        config_data = response.json()

        # 更新缓存
        _tmdb_config_cache.update({
            "api_key": config_data.get("tmdb_api_key", ""),
            "base_url": config_data.get("tmdb_base_url", TMDB_DEFAULT_BASE_URL),
            "image_base_url": config_data.get("tmdb_image_base_url", TMDB_DEFAULT_IMAGE_BASE_URL),
            "language": config_data.get("tmdb_language", TMDB_DEFAULT_LANGUAGE),
            "cache_time": datetime.now()
        })

        logger.info("TMDB 配置已从 admin backend 加载")

    except Exception as e:
        logger.warning(f"从 admin backend 加载 TMDB 配置失败: {e}，使用默认值或环境变量")

        # 回退到环境变量
        _tmdb_config_cache.update({
            "api_key": os.getenv("TMDB_API_KEY", ""),
            "base_url": os.getenv("TMDB_BASE_URL", TMDB_DEFAULT_BASE_URL),
            "image_base_url": os.getenv("TMDB_IMAGE_BASE_URL", TMDB_DEFAULT_IMAGE_BASE_URL),
            "language": os.getenv("TMDB_LANGUAGE", TMDB_DEFAULT_LANGUAGE),
            "cache_time": datetime.now()
        })

    return {
        "api_key": _tmdb_config_cache["api_key"],
        "base_url": _tmdb_config_cache["base_url"],
        "image_base_url": _tmdb_config_cache["image_base_url"],
        "language": _tmdb_config_cache["language"],
    }


def get_tmdb_config() -> Dict[str, str]:
    """获取 TMDB 配置（带缓存）"""
    return _load_tmdb_config()


def clear_tmdb_config_cache():
    """清除 TMDB 配置缓存（用于配置更新后刷新）"""
    global _tmdb_config_cache
    _tmdb_config_cache["cache_time"] = None


class TMDBService:
    """TMDB API 服务类"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化 TMDB 服务

        Args:
            api_key: 可选的 API Key，如果不提供则从配置系统获取
        """
        config = get_tmdb_config()
        self.api_key = api_key or config["api_key"]
        self.base_url = config["base_url"]
        self.image_base_url = config["image_base_url"]
        self.default_language = config["language"]
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    def _get_poster_url(self, path: str, size: str = "w342") -> Optional[str]:
        """
        获取海报完整 URL

        Args:
            path: 海报路径
            size: 图片尺寸 (w92, w154, w185, w342, w500, w780, original)
        """
        if not path:
            return None
        return f"{self.image_base_url}/{size}{path}"

    async def search_multi(
        self,
        query: str,
        language: Optional[str] = None,
        page: int = 1
    ) -> List[Dict[str, Any]]:
        """
        搜索影片（电影和剧集）

        Args:
            query: 搜索关键词
            language: 语言代码（不指定则使用配置的默认语言）
            page: 页码

        Returns:
            搜索结果列表
        """
        if not self.api_key:
            logger.warning("TMDB API_KEY 未配置")
            return []

        if not query or len(query.strip()) < 2:
            return []

        lang = language or self.default_language

        try:
            response = await self.client.get(
                f"{self.base_url}/search/multi",
                params={
                    "api_key": self.api_key,
                    "query": query,
                    "language": lang,
                    "page": page,
                    "include_adult": "false"
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                media_type = item.get("media_type")
                if media_type not in ("movie", "tv"):
                    continue

                poster_path = item.get("poster_path")
                results.append({
                    "id": item.get("id"),
                    "tmdb_id": item.get("id"),
                    "media_type": "movie" if media_type == "movie" else "series",
                    "title": item.get("title") or item.get("name"),
                    "original_title": item.get("original_title") or item.get("original_name"),
                    "year": self._extract_year(item.get("release_date") or item.get("first_air_date")),
                    "overview": item.get("overview"),
                    "poster_url": self._get_poster_url(poster_path, "w342"),
                    "poster_url_large": self._get_poster_url(poster_path, "w500"),
                    "backdrop_url": self._get_poster_url(item.get("backdrop_path"), "w780"),
                    "vote_average": item.get("vote_average"),
                    "vote_count": item.get("vote_count"),
                    "genre_ids": item.get("genre_ids", []),
                })

            return results

        except httpx.HTTPError as e:
            logger.error(f"TMDB 搜索请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"TMDB 搜索解析失败: {e}")
            return []

    async def search_movie(
        self,
        query: str,
        language: Optional[str] = None,
        page: int = 1
    ) -> List[Dict[str, Any]]:
        """
        搜索电影

        Args:
            query: 搜索关键词
            language: 语言代码
            page: 页码

        Returns:
            搜索结果列表
        """
        if not self.api_key:
            logger.warning("TMDB API_KEY 未配置")
            return []

        if not query or len(query.strip()) < 2:
            return []

        lang = language or self.default_language

        try:
            response = await self.client.get(
                f"{self.base_url}/search/movie",
                params={
                    "api_key": self.api_key,
                    "query": query,
                    "language": lang,
                    "page": page,
                    "include_adult": "false"
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                poster_path = item.get("poster_path")
                results.append({
                    "id": item.get("id"),
                    "tmdb_id": item.get("id"),
                    "media_type": "movie",
                    "title": item.get("title"),
                    "original_title": item.get("original_title"),
                    "year": self._extract_year(item.get("release_date")),
                    "overview": item.get("overview"),
                    "poster_url": self._get_poster_url(poster_path, "w342"),
                    "poster_url_large": self._get_poster_url(poster_path, "w500"),
                    "backdrop_url": self._get_poster_url(item.get("backdrop_path"), "w780"),
                    "vote_average": item.get("vote_average"),
                    "vote_count": item.get("vote_count"),
                    "genre_ids": item.get("genre_ids", []),
                })

            return results

        except httpx.HTTPError as e:
            logger.error(f"TMDB 电影搜索请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"TMDB 电影搜索解析失败: {e}")
            return []

    async def search_tv(
        self,
        query: str,
        language: Optional[str] = None,
        page: int = 1
    ) -> List[Dict[str, Any]]:
        """
        搜索剧集

        Args:
            query: 搜索关键词
            language: 语言代码
            page: 页码

        Returns:
            搜索结果列表
        """
        if not self.api_key:
            logger.warning("TMDB API_KEY 未配置")
            return []

        if not query or len(query.strip()) < 2:
            return []

        lang = language or self.default_language

        try:
            response = await self.client.get(
                f"{self.base_url}/search/tv",
                params={
                    "api_key": self.api_key,
                    "query": query,
                    "language": lang,
                    "page": page,
                    "include_adult": "false"
                }
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("results", []):
                poster_path = item.get("poster_path")
                results.append({
                    "id": item.get("id"),
                    "tmdb_id": item.get("id"),
                    "media_type": "series",
                    "title": item.get("name"),
                    "original_title": item.get("original_name"),
                    "year": self._extract_year(item.get("first_air_date")),
                    "overview": item.get("overview"),
                    "poster_url": self._get_poster_url(poster_path, "w342"),
                    "poster_url_large": self._get_poster_url(poster_path, "w500"),
                    "backdrop_url": self._get_poster_url(item.get("backdrop_path"), "w780"),
                    "vote_average": item.get("vote_average"),
                    "vote_count": item.get("vote_count"),
                    "genre_ids": item.get("genre_ids", []),
                })

            return results

        except httpx.HTTPError as e:
            logger.error(f"TMDB 剧集搜索请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"TMDB 剧集搜索解析失败: {e}")
            return []

    async def get_movie_details(
        self,
        tmdb_id: int,
        language: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取电影详情

        Args:
            tmdb_id: TMDB ID
            language: 语言代码

        Returns:
            影片详情
        """
        if not self.api_key:
            logger.warning("TMDB API_KEY 未配置")
            return None

        lang = language or self.default_language

        try:
            response = await self.client.get(
                f"{self.base_url}/movie/{tmdb_id}",
                params={
                    "api_key": self.api_key,
                    "language": lang
                }
            )
            response.raise_for_status()
            item = response.json()

            poster_path = item.get("poster_path")
            return {
                "id": item.get("id"),
                "tmdb_id": item.get("id"),
                "media_type": "movie",
                "title": item.get("title"),
                "original_title": item.get("original_title"),
                "year": self._extract_year(item.get("release_date")),
                "overview": item.get("overview"),
                "poster_url": self._get_poster_url(poster_path, "w342"),
                "poster_url_large": self._get_poster_url(poster_path, "w500"),
                "backdrop_url": self._get_poster_url(item.get("backdrop_path"), "w780"),
                "vote_average": item.get("vote_average"),
                "vote_count": item.get("vote_count"),
                "runtime": item.get("runtime"),
                "genres": [g.get("name") for g in item.get("genres", [])],
                "release_date": item.get("release_date"),
                "status": item.get("status"),
            }

        except httpx.HTTPError as e:
            logger.error(f"获取 TMDB 电影详情失败: {e}")
            return None
        except Exception as e:
            logger.error(f"解析 TMDB 电影详情失败: {e}")
            return None

    async def get_tv_details(
        self,
        tmdb_id: int,
        language: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取剧集详情

        Args:
            tmdb_id: TMDB ID
            language: 语言代码

        Returns:
            影片详情
        """
        if not self.api_key:
            logger.warning("TMDB API_KEY 未配置")
            return None

        lang = language or self.default_language

        try:
            response = await self.client.get(
                f"{self.base_url}/tv/{tmdb_id}",
                params={
                    "api_key": self.api_key,
                    "language": lang
                }
            )
            response.raise_for_status()
            item = response.json()

            poster_path = item.get("poster_path")
            return {
                "id": item.get("id"),
                "tmdb_id": item.get("id"),
                "media_type": "series",
                "title": item.get("name"),
                "original_title": item.get("original_name"),
                "year": self._extract_year(item.get("first_air_date")),
                "overview": item.get("overview"),
                "poster_url": self._get_poster_url(poster_path, "w342"),
                "poster_url_large": self._get_poster_url(poster_path, "w500"),
                "backdrop_url": self._get_poster_url(item.get("backdrop_path"), "w780"),
                "vote_average": item.get("vote_average"),
                "vote_count": item.get("vote_count"),
                "genres": [g.get("name") for g in item.get("genres", [])],
                "first_air_date": item.get("first_air_date"),
                "number_of_seasons": item.get("number_of_seasons"),
                "number_of_episodes": item.get("number_of_episodes"),
                "status": item.get("status"),
            }

        except httpx.HTTPError as e:
            logger.error(f"获取 TMDB 剧集详情失败: {e}")
            return None
        except Exception as e:
            logger.error(f"解析 TMDB 剧集详情失败: {e}")
            return None

    def _extract_year(self, date_str: Optional[str]) -> Optional[str]:
        """从日期字符串中提取年份"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str).year
        except:
            return None


# 全局实例
_tmdb_service: Optional[TMDBService] = None


def get_tmdb_service() -> TMDBService:
    """获取 TMDB 服务实例（单例，每次调用重新获取配置）"""
    # 每次都创建新实例以确保获取最新配置
    return TMDBService()
