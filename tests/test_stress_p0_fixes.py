"""压力测试 P0/P1 修复的回归测试（2026-10-07）"""


def test_db_pool_size_increased():
    """P0-1：DB 连接池从 10+10 提高到 25+25"""
    from backend import database
    assert database._POOL_SIZE >= 25
    assert database._MAX_OVERFLOW >= 25


def test_janitor_runs_gc():
    """P0-2：janitor 维护周期包含 gc.collect()"""
    import inspect
    from backend.emby_server import maintenance
    src = inspect.getsource(maintenance.start_janitor)
    assert "gc.collect()" in src


def test_postgres_max_connections():
    """P0-1：docker-compose.yml 里 PG max_connections>=200"""
    with open("docker-compose.yml") as f:
        text = f.read()
    assert "max_connections=200" in text
