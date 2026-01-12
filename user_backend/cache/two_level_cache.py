"""
Two-Level Cache Implementation

L1 (Level 1): In-memory cache using dictionary
L2 (Level 2): Redis cache for distributed scenarios

Cache Strategy:
1. Check L1 cache first (fastest)
2. If not in L1, check L2 cache
3. If not in L2, fetch from source
4. Store in both L1 and L2
5. L1 has shorter TTL, L2 has longer TTL
"""
import asyncio
import json
import time
import hashlib
import logging
from typing import Optional, Any, Callable, TypeVar, Union
from functools import wraps
from dataclasses import dataclass

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry:
    """A cached value with expiration."""
    value: Any
    expires_at: float

    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        return time.time() > self.expires_at


class L1Cache:
    """
    Level 1 cache - in-memory dictionary cache.

    Fast, local to each instance, limited size.
    """

    def __init__(self, max_size: int = 1000, default_ttl: int = 60):
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        """Get value from L1 cache."""
        async with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in L1 cache."""
        async with self._lock:
            # Enforce max size by removing oldest entries
            if len(self._cache) >= self._max_size and key not in self._cache:
                self._evict_oldest()

            ttl = ttl or self._default_ttl
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.time() + ttl
            )
            return True

    async def delete(self, key: str) -> bool:
        """Delete value from L1 cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self) -> None:
        """Clear all entries from L1 cache."""
        async with self._lock:
            self._cache.clear()

    def _evict_oldest(self) -> None:
        """Remove oldest entry when cache is full."""
        # Simple FIFO eviction
        if self._cache:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }


class L2Cache:
    """
    Level 2 cache - Redis distributed cache.

    Shared across all instances, larger capacity.
    """

    def __init__(self, default_ttl: int = 3600):
        self._default_ttl = default_ttl
        self._redis = None
        self._enabled = False

    async def _get_redis(self):
        """Lazy load Redis client."""
        if self._redis is None:
            from utils.redis_client import get_redis_client
            self._redis = await get_redis_client()
            self._enabled = self._redis is not None
        return self._redis

    def _serialize(self, value: Any) -> str:
        """Serialize value for storage."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            return str(value)
        return json.dumps(value)

    def _deserialize(self, value: str) -> Any:
        """Deserialize value from storage."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value

    async def get(self, key: str) -> Optional[Any]:
        """Get value from L2 cache (Redis)."""
        if not self._enabled:
            return None

        try:
            redis = await self._get_redis()
            if not redis:
                return None

            value = await redis.get(f"l2:{key}")
            if value:
                return self._deserialize(value)
            return None

        except Exception as e:
            logger.warning(f"L2 cache get error: {e}")
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ) -> bool:
        """Set value in L2 cache (Redis)."""
        if not self._enabled:
            return False

        try:
            redis = await self._get_redis()
            if not redis:
                return False

            ttl = ttl or self._default_ttl
            serialized = self._serialize(value)
            await redis.setex(f"l2:{key}", ttl, serialized)
            return True

        except Exception as e:
            logger.warning(f"L2 cache set error: {e}")
            return False

    async def delete(self, key: str) -> bool:
        """Delete value from L2 cache."""
        if not self._enabled:
            return False

        try:
            redis = await self._get_redis()
            if not redis:
                return False

            await redis.delete(f"l2:{key}")
            return True

        except Exception as e:
            logger.warning(f"L2 cache delete error: {e}")
            return False

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern."""
        if not self._enabled:
            return 0

        try:
            redis = await self._get_redis()
            if not redis:
                return 0

            keys = await redis.keys(f"l2:{pattern}")
            if keys:
                await redis.delete(*keys)
            return len(keys)

        except Exception as e:
            logger.warning(f"L2 cache clear pattern error: {e}")
            return 0


class TwoLevelCache:
    """
    Two-level cache manager.

    Coordinates L1 and L2 caches for optimal performance.
    """

    def __init__(
        self,
        l1_max_size: int = 1000,
        l1_ttl: int = 60,
        l2_ttl: int = 3600
    ):
        self.l1 = L1Cache(max_size=l1_max_size, default_ttl=l1_ttl)
        self.l2 = L2Cache(default_ttl=l2_ttl)

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Checks L1 first, then L2.
        Populates L1 from L2 on cache miss.
        """
        # Try L1 first
        value = await self.l1.get(key)
        if value is not None:
            return value

        # Try L2
        value = await self.l2.get(key)
        if value is not None:
            # Populate L1
            await self.l1.set(key, value)
            return value

        return None

    async def set(
        self,
        key: str,
        value: Any,
        l1_ttl: Optional[int] = None,
        l2_ttl: Optional[int] = None
    ) -> bool:
        """Set value in both L1 and L2 caches."""
        l1_success = await self.l1.set(key, value, ttl=l1_ttl)
        l2_success = await self.l2.set(key, value, ttl=l2_ttl)
        return l1_success or l2_success

    async def delete(self, key: str) -> bool:
        """Delete value from both caches."""
        l1_deleted = await self.l1.delete(key)
        l2_deleted = await self.l2.delete(key)
        return l1_deleted or l2_deleted

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all cache entries matching pattern.

        Only affects L2 (Redis) since L1 is local.
        """
        # Clear L1 entirely for simplicity
        await self.l1.clear()
        # Clear matching L2 keys
        return await self.l2.clear_pattern(pattern)

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        l1_ttl: Optional[int] = None,
        l2_ttl: Optional[int] = None
    ) -> Any:
        """
        Get value from cache or compute using factory function.

        Args:
            key: Cache key
            factory: Async function to compute value if not cached
            l1_ttl: Optional TTL for L1 cache
            l2_ttl: Optional TTL for L2 cache

        Returns:
            Cached or computed value
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()

        # Store in cache
        await self.set(key, value, l1_ttl=l1_ttl, l2_ttl=l2_ttl)
        return value

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "l1": self.l1.get_stats(),
            "l2_enabled": self.l2._enabled,
        }


# Global cache instance
_default_cache: Optional[TwoLevelCache] = None


def get_cache() -> TwoLevelCache:
    """Get the default cache instance."""
    global _default_cache
    if _default_cache is None:
        _default_cache = TwoLevelCache()
    return _default_cache


def cache_result(
    key_prefix: str,
    l1_ttl: int = 60,
    l2_ttl: int = 3600,
    key_func: Optional[Callable[..., str]] = None
):
    """
    Decorator to cache function results.

    Args:
        key_prefix: Prefix for cache keys
        l1_ttl: Time-to-live for L1 cache (seconds)
        l2_ttl: Time-to-live for L2 cache (seconds)
        key_func: Optional function to generate cache key from args

    Example:
        @cache_result("user_profile", l1_ttl=60, l2_ttl=600)
        async def get_user_profile(user_id: int):
            return await db.get_user(user_id)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            cache = get_cache()

            # Generate cache key
            if key_func:
                key_suffix = key_func(*args, **kwargs)
            else:
                # Use args and kwargs to generate key
                key_parts = [str(a) for a in args]
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_suffix = hashlib.md5(
                    ":".join(key_parts).encode()
                ).hexdigest()[:16]

            cache_key = f"{key_prefix}:{key_suffix}"

            # Try to get from cache
            value = await cache.get(cache_key)
            if value is not None:
                return value

            # Call function
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Store in cache
            await cache.set(cache_key, result, l1_ttl=l1_ttl, l2_ttl=l2_ttl)

            return result

        return wrapper

    return decorator


# Convenience decorators for common patterns
def cached(ttl: int = 300, key_prefix: Optional[str] = None):
    """
    Simple cache decorator.

    Args:
        ttl: Cache time-to-live in seconds
        key_prefix: Optional key prefix (defaults to function name)

    Example:
        @cached(ttl=600)
        async def get_config():
            return await fetch_config()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        prefix = key_prefix or func.__name__
        return cache_result(prefix, l1_ttl=ttl, l2_ttl=ttl * 10)(func)

    return decorator


def fast_cache(ttl: int = 60):
    """L1-only cache for very frequently accessed data."""
    return cache_result("", l1_ttl=ttl, l2_ttl=0)


def slow_cache(ttl: int = 3600):
    """L2-only cache for rarely changing data."""
    return cache_result("", l1_ttl=0, l2_ttl=ttl)
