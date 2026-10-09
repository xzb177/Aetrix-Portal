"""callback_query 处理（B3 实现抢红包按钮，B1 占位）。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def handle_callback(db, callback_query: dict) -> None:
    """处理 callback_query。B1 暂不实现，B3 接抢红包按钮。"""
    logger.debug("callback_query received (not implemented in B1)")
