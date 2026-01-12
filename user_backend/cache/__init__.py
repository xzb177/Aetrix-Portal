"""
Two-level caching system for RoyalBot Portal.

L1 Cache: In-memory cache (fast, local to instance)
L2 Cache: Redis cache (shared across all instances)

This provides:
- Fast local cache for frequently accessed data
- Distributed cache for multi-instance deployments
- Automatic cache invalidation
- Graceful degradation when cache is unavailable
"""
from .two_level_cache import TwoLevelCache, cache_result, cached

__all__ = ["TwoLevelCache", "cache_result", "cached"]
