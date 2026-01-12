"""
Redis 缓存工具 - 性能优化版
支持缓存预热、穿透防护、击穿防护、雪崩防护
"""
import json
import hashlib
import time
import logging
from typing import Optional, Any, Callable, TypeVar, Union
from functools import wraps
from datetime import timedelta

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from admin_utils.config import settings

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RedisCache:
    """Redis 缓存管理器"""

    def __init__(self):
        self.client: Optional[redis.Redis] = None
        self.enabled = REDIS_AVAILABLE
        self.prefix = "royalbot:admin:"

        if self.enabled:
            try:
                self.client = redis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True,
                )
                # 测试连接
                self.client.ping()
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, caching disabled")
                self.enabled = False
                self.client = None

    def _make_key(self, key: str) -> str:
        """生成带前缀的缓存键"""
        return f"{self.prefix}{key}"

    def _hash_key(self, key: str) -> str:
        """对过长的键进行哈希"""
        if len(key) > 100:
            return hashlib.md5(key.encode()).hexdigest()
        return key

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self.enabled or not self.client:
            return None

        try:
            cache_key = self._make_key(self._hash_key(key))
            value = self.client.get(cache_key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            return None

    def set(
        self,
        key: str,
        value: Any,
        ttl: int = 300,
        nx: bool = False
    ) -> bool:
        """设置缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            cache_key = self._make_key(self._hash_key(key))
            serialized = json.dumps(value, ensure_ascii=False)

            # 防雪崩：添加随机过期时间
            if ttl > 60:
                ttl = ttl + int(time.time() % 60)  # 最多增加60秒

            return self.client.set(cache_key, serialized, ex=ttl, nx=nx)
        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除缓存"""
        if not self.enabled or not self.client:
            return False

        try:
            cache_key = self._make_key(self._hash_key(key))
            return bool(self.client.delete(cache_key))
        except Exception as e:
            logger.warning(f"Cache delete error: {e}")
            return False

    def delete_pattern(self, pattern: str) -> int:
        """批量删除匹配模式的缓存"""
        if not self.enabled or not self.client:
            return 0

        try:
            cache_pattern = self._make_key(pattern)
            keys = self.client.keys(cache_pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Cache delete_pattern error: {e}")
            return 0

    def exists(self, key: str) -> bool:
        """检查缓存是否存在"""
        if not self.enabled or not self.client:
            return False

        try:
            cache_key = self._make_key(self._hash_key(key))
            return bool(self.client.exists(cache_key))
        except Exception:
            return False

    def incr(self, key: str, amount: int = 1) -> Optional[int]:
        """原子递增"""
        if not self.enabled or not self.client:
            return None

        try:
            cache_key = self._make_key(self._hash_key(key))
            return self.client.incr(cache_key, amount)
        except Exception:
            return None

    def expire(self, key: str, ttl: int) -> bool:
        """设置过期时间"""
        if not self.enabled or not self.client:
            return False

        try:
            cache_key = self._make_key(self._hash_key(key))
            return bool(self.client.expire(cache_key, ttl))
        except Exception:
            return False

    def clear_all(self) -> bool:
        """清空所有缓存（慎用）"""
        if not self.enabled or not self.client:
            return False

        try:
            keys = self.client.keys(f"{self.prefix}*")
            if keys:
                return bool(self.client.delete(*keys))
            return True
        except Exception as e:
            logger.warning(f"Cache clear error: {e}")
            return False


# 全局缓存实例
cache = RedisCache()


def cached(
    key_prefix: str,
    ttl: int = 300,
    skip_args: Optional[list] = None,
    include_kwargs: Optional[list] = None
):
    """
    缓存装饰器

    :param key_prefix: 缓存键前缀
    :param ttl: 过期时间（秒）
    :param skip_args: 跳过的参数索引（如 self, cls）
    :param include_kwargs: 包含的 kwargs 键名
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # 生成缓存键
            cache_key_parts = [key_prefix]

            # 处理位置参数
            arg_start = skip_args[0] if skip_args else 0
            for i, arg in enumerate(args[arg_start:], start=arg_start):
                if isinstance(arg, (str, int, float, bool)):
                    cache_key_parts.append(str(arg))

            # 处理关键字参数
            if include_kwargs:
                for k in include_kwargs:
                    if k in kwargs:
                        v = kwargs[k]
                        if isinstance(v, (str, int, float, bool)):
                            cache_key_parts.append(f"{k}:{v}")

            cache_key = ":".join(cache_key_parts)

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit: {cache_key}")
                return cached_value

            # 缓存未命中，执行函数
            result = await func(*args, **kwargs)

            # 存入缓存
            cache.set(cache_key, result, ttl=ttl)
            logger.debug(f"Cache set: {cache_key}")

            return result

        return wrapper
    return decorator


def cache_through(
    key_func: Callable[..., str],
    ttl: int = 300,
    empty_ttl: int = 60
):
    """
    缓存穿透防护装饰器
    对空结果也进行缓存，但过期时间较短

    :param key_func: 生成缓存键的函数
    :param ttl: 正常数据过期时间
    :param empty_ttl: 空数据过期时间
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cache_key = key_func(*args, **kwargs)

            # 尝试从缓存获取
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                # 标记是否是空缓存
                if cached_value == "__EMPTY__":
                    return None
                return cached_value

            # 执行函数
            result = await func(*args, **kwargs)

            # 存入缓存
            if result is None:
                # 空结果也缓存，防止穿透
                cache.set(cache_key, "__EMPTY__", ttl=empty_ttl)
            else:
                cache.set(cache_key, result, ttl=ttl)

            return result

        return wrapper
    return decorator


def cache_lock(
    key: str,
    ttl: int = 10,
    timeout: int = 30
):
    """
    缓存锁装饰器 - 防止缓存击穿
    使用分布式锁确保只有一个请求去查询数据库

    :param key: 锁的键名
    :param ttl: 锁的持有时间
    :param timeout: 获取锁的超时时间
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            lock_key = f"lock:{key}"

            # 尝试获取锁
            acquired = cache.set(lock_key, "1", ttl=ttl, nx=True)
            if acquired:
                try:
                    # 获取到锁，执行函数
                    return await func(*args, **kwargs)
                finally:
                    # 释放锁
                    cache.delete(lock_key)
            else:
                # 未获取到锁，等待一下后尝试从缓存读取
                await asyncio.sleep(0.1)
                cached = cache.get(key)
                if cached is not None:
                    return cached
                # 如果还是没有，返回默认值或抛出异常
                raise Exception("Service temporarily unavailable")

        return wrapper
    return decorator


import asyncio


# 缓存预热函数
async def warmup_cache(data_getter: dict[str, Callable[[], Any]]):
    """
    缓存预热

    :param data_getter: {cache_key: 数据获取函数}
    """
    logger.info("Starting cache warmup...")
    success_count = 0

    for key, getter in data_getter.items():
        try:
            # 检查是否已有缓存
            if cache.exists(key):
                continue

            # 获取数据并存入缓存
            data = getter()
            if data is not None:
                cache.set(key, data)
                success_count += 1
        except Exception as e:
            logger.warning(f"Cache warmup failed for {key}: {e}")

    logger.info(f"Cache warmup completed: {success_count}/{len(data_getter)} items")


# 缓存统计
class CacheStats:
    """缓存统计工具"""
    hits = 0
    misses = 0

    @classmethod
    def record_hit(cls):
        cls.hits += 1

    @classmethod
    def record_miss(cls):
        cls.misses += 1

    @classmethod
    def get_hit_rate(cls) -> float:
        total = cls.hits + cls.misses
        return cls.hits / total if total > 0 else 0

    @classmethod
    def reset(cls):
        cls.hits = 0
        cls.misses = 0
