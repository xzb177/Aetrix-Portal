"""安全 / 恢复 / 清理三份补丁合并后的护栏：恢复的功能依赖的代码不能被「零引用清理」删掉。"""
import importlib
import os
import pkgutil

os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("REDIS_ENABLED", "false")


def test_refresh_person_worker_importable_and_startable():
    mod = importlib.import_module("backend.emby_server.refresh_person_worker")
    assert callable(mod.start) and callable(mod.stop) and callable(mod.run_once)


def test_mediainfo_delete_json_kept_for_scanner(tmp_path, monkeypatch):
    from backend.emby_server import mediainfo_persist as mp

    f = tmp_path / "x.json"
    f.write_text("{}")
    monkeypatch.setattr(mp, "get_json_path", lambda item: str(f))
    mp.delete_json(object())
    assert not f.exists()
    mp.delete_json(object())  # 不存在时静默


def test_all_emby_server_modules_import():
    import backend.emby_server as pkg

    failures = []
    for info in pkgutil.iter_modules(pkg.__path__):
        name = f"backend.emby_server.{info.name}"
        try:
            importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - 失败时给出清单
            failures.append(f"{name}: {exc!r}")
    assert failures == []
