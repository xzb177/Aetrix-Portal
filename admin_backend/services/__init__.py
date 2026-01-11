"""
Services package - MoviePilot 集成
"""
from .moviepilot import (
    MoviePilotClient,
    test_moviepilot,
    add_subscribe,
    get_subscribes,
    SubscribeResult
)

__all__ = [
    "MoviePilotClient",
    "test_moviepilot",
    "add_subscribe",
    "get_subscribes",
    "SubscribeResult"
]
