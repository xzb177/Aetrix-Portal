"""热点列表端点的 JSON 序列化（审查 P4）

FastAPI 对返回 dict 的路由会先 ``jsonable_encoder``（递归遍历整个响应、逐值判类型）再
``json.dumps``——两步都在**事件循环**上做（不论路由是 sync 还是 async）：100 条电影
约 12ms、1000 集约 80–100ms 的纯 CPU 卡在单 worker 的事件循环上。

这里让热点端点直接返回 :class:`FastJSONResponse`：

- FastAPI 看到返回值已是 ``Response`` 就原样发送，跳过 ``jsonable_encoder``；
- 端点是 sync ``def`` 时响应在线程池里构造，序列化随之离开事件循环；
- ``orjson`` 比标准库快约 40 倍（审查实测 100 条电影 0.26ms vs 1.4ms + 11.7ms）。

输出与 ``JSONResponse`` 同口径：UTF-8、不转义非 ASCII、紧凑分隔符。orjson 不认识的类型
（以及 datetime / dataclass，保证与升级前逐字一致）交给 ``jsonable_encoder`` 兜底。
已知的字节级差异只在极端浮点格式上（``1e+16`` → ``1e16``），JSON 语义相同；NaN 由
「500」变成 ``null``（标准库 allow_nan=False 会直接抛错）。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any

import orjson
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

_OPTIONS = (orjson.OPT_NON_STR_KEYS | orjson.OPT_PASSTHROUGH_DATETIME
            | orjson.OPT_PASSTHROUGH_DATACLASS)


def _default(obj: Any) -> Any:
    encoded = jsonable_encoder(obj)
    if encoded is obj:  # 防御：避免无限递归
        raise TypeError(f"无法序列化 {type(obj).__name__}")
    return encoded


def dumps(content: Any) -> bytes:
    return orjson.dumps(content, default=_default, option=_OPTIONS)


class FastJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return dumps(content)


def _to_response(result):
    if isinstance(result, (dict, list)):
        return FastJSONResponse(result)
    return result


def json_route(router, *paths: str, **route_kwargs):
    """``@router.get(p1) @router.get(p2) …`` 的替身：路由注册包了 orjson 的版本，
    **模块里的名字仍是原函数**（返回 dict / list），其它模块与测试直接调用不受影响。
    """
    def deco(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def endpoint(*args, **kwargs):
                return _to_response(await fn(*args, **kwargs))
        else:
            @functools.wraps(fn)
            def endpoint(*args, **kwargs):
                return _to_response(fn(*args, **kwargs))
        endpoint.__fast_json__ = True
        # 与装饰器叠放的注册顺序一致（下面的装饰器先注册）
        for path in reversed(paths):
            router.get(path, **route_kwargs)(endpoint)
        return fn
    return deco
