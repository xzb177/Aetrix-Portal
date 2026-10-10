"""群抽奖手动开奖必须调用 notify_draw_results（回归测试）。

背景：管理后台"开奖"按钮走 POST /welfare/lottery/rounds/{id}/draw，
之前只调 draw_round + distribute_round，漏掉了 notify_draw_results，
导致群里收不到开奖公告（自动开奖 run_due_draws 有调，不受影响）。

本测试用 AST 静态断言：draw_lottery_round 函数体内必须出现
notify_draw_results 调用，防止将来重构时再次漏掉。
"""
import ast
import sys

sys.path.insert(0, ".")


def _get_func_node(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _calls_notify(func_node):
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "notify_draw_results":
                return True
            if isinstance(f, ast.Name) and f.id == "notify_draw_results":
                return True
    return False


def test_manual_draw_calls_notify():
    """draw_lottery_round 必须调用 notify_draw_results。"""
    with open("backend/api/welfare_admin.py", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = _get_func_node(tree, "draw_lottery_round")
    assert func is not None, "找不到 draw_lottery_round 函数"
    assert _calls_notify(func), (
        "draw_lottery_round 没有调用 notify_draw_results！"
        "手动开奖后群里收不到开奖公告（回归）。"
    )


def test_auto_draw_still_calls_notify():
    """自动开奖 run_due_draws 必须继续调用 notify_draw_results（防回归）。"""
    with open("backend/lottery.py", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    func = _get_func_node(tree, "run_due_draws")
    assert func is not None, "找不到 run_due_draws 函数"
    assert _calls_notify(func), "run_due_draws 没有调用 notify_draw_results（回归）。"
