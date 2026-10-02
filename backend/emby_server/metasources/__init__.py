"""多源元数据补全（Phase 6b）

| 模块 | 职责 |
|---|---|
| ``config`` | SystemConfig ↔ 配置快照（总开关 / 中文优先 / 顺序 / 逐源开关与密钥池） |
| ``keypool`` | 通用密钥池（轮转 + 逐把冷却）与逐源限速闸 |
| ``sources`` | 七个源的客户端与统一命中结构 ``Hit`` |
| ``engine`` | 按顺序取字段 · 失败隔离 · 外部 ID 合并 · 落库 |

总开关 ``meta_sources_enabled`` 关闭时，这个包**一次网络请求都不发**：
补全链路走原来的 NFO → TMDB → 豆瓣/Bangumi 兜底，行为与升级前一致。
"""

__all__ = ["config", "engine", "keypool", "sources"]