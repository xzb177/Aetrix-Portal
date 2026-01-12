"""
Redis client utility for RoyalBot Portal.

Provides a singleton Redis client with connection pooling and graceful degradation.
"""
import os
from typing import Optional
import redis.asyncio as aioredis
from redis.exceptions import RedisError
import logging

logger = logging.getLogger(__name__)

# Singleton Redis client
_redis_client: Optional[aioredis.Redis] = None


def get_redis_url() -> str:
    """Get Redis URL from environment."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        # Default to localhost
        redis_url = "redis://:redis_change_me@localhost:6379/0"
    return redis_url


async def get_redis_client() -> Optional[aioredis.Redis]:
    """
    Get or create the Redis client.

    Returns None if Redis is not configured or connection fails,
    allowing graceful degradation.
    """
    global _redis_client

    # Check if Redis is enabled
    if os.getenv("REDIS_ENABLED", "true").lower() != "true":
        return None

    # Return existing client if available
    if _redis_client is not None:
        try:
            # Test connection
            await _redis_client.ping()
            return _redis_client
        except RedisError:
            logger.warning("Redis connection lost, attempting reconnect...")
            _redis_client = None

    # Create new client
    redis_url = get_redis_url()

    try:
        _redis_client = await aioredis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        # Test connection
        await _redis_client.ping()
        logger.info("Redis client initialized successfully")
        return _redis_client

    except (RedisError, OSError) as e:
        logger.warning(f"Redis connection failed: {e}. Running without Redis cache.")
        _redis_client = None
        return None


async def close_redis():
    """Close the Redis connection."""
    global _redis_client
    if _redis_client:
        try:
            await _redis_client.close()
            _redis_client = None
            logger.info("Redis connection closed")
        except RedisError as e:
            logger.warning(f"Error closing Redis: {e}")


# Synchronous wrapper for non-async contexts
class SyncRedisWrapper:
    """Synchronous wrapper for Redis operations."""

    def __init__(self):
        import redis
        self._client: Optional[redis.Redis] = None
        self._init_client()

    def _init_client(self):
        """Initialize synchronous Redis client."""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://:redis_change_me@localhost:6379/0")
            # Parse URL for redis.Redis
            if redis_url.startswith("redis://"):
                # Extract password and host from URL
                import re
                match = re.match(r'redis://:([^@]+)@([^:]+):(\d+)/(\d+)', redis_url)
                if match:
                    password, host, port, db = match.groups()
                    self._client = redis.Redis(
                        host=host,
                        port=int(port),
                        db=int(db),
                        password=password,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                    )
                else:
                    self._client = None
            else:
                self._client = None

            if self._client:
                self._client.ping()
                logger.info("Sync Redis client initialized")

        except Exception as e:
            logger.warning(f"Sync Redis connection failed: {e}")
            self._client = None

    @property
    def available(self) -> bool:
        """Check if Redis is available."""
        return self._client is not None

    def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        if not self._client:
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set value in Redis."""
        if not self._client:
            return False
        try:
            return self._client.set(key, value, ex=ex)
        except Exception as e:
            logger.warning(f"Redis set error: {e}")
            return False

    def delete(self, *keys: str) -> int:
        """Delete keys from Redis."""
        if not self._client:
            return 0
        try:
            return self._client.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis delete error: {e}")
            return 0

    def exists(self, key: str) -> bool:
        """Check if key exists in Redis."""
        if not self._client:
            return False
        try:
            return bool(self._client.exists(key))
        except Exception as e:
            logger.warning(f"Redis exists error: {e}")
            return False

    def incr(self, key: str) -> Optional[int]:
        """Increment value in Redis."""
        if not self._client:
            return None
        try:
            return self._client.incr(key)
        except Exception as e:
            logger.warning(f"Redis incr error: {e}")
            return None

    def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on key."""
        if not self._client:
            return False
        try:
            return self._client.expire(key, seconds)
        except Exception as e:
            logger.warning(f"Redis expire error: {e}")
            return False


# Singleton sync client
_sync_redis: Optional[SyncRedisWrapper] = None


def get_sync_redis() -> SyncRedisWrapper:
    """Get or create synchronous Redis client."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = SyncRedisWrapper()
    return _sync_redis
