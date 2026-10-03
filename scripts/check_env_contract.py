#!/usr/bin/env python3
"""授权版环境变量契约门禁：挡住「照文档走仍然起不来」的配置事故

背景（v2.42.11）：授权客户的部署动作只有「照 DEPLOY.md 敲四条命令」。
所以**文档与 env.example 之间的任何不一致，都是启动阻断**，
而不是文档瑕疵。v2.42.10 之前就有两处真的把客户卡住了（均已用真容器复现）：

1. `env.example` 里写死 `DATABASE_URL=postgresql://aetrix:aetrix@...`，
   而 DEPLOY.md 让客户用 sed 改 `POSTGRES_PASSWORD` —— 两边密码从此不一致，
   后端一直报 `password authentication failed`，容器反复重启。
   实测：起真 PostgreSQL，用 aetrix 连 → FATAL；用 sed 后的密码连 → 成功。
2. `env.example` 里 `REDIS_ENABLED=false`，而 compose 的健康检查硬断言
   Redis 里有 worker 心跳，且 `backend/worker.py` 在 `REDIS_ENABLED=false`
   时直接 `return 1` 拒绝启动 —— 服务永远不可能 healthy。
   实测：真跑 worker → 「Redis 不可用…worker 拒绝启动」。

这两处的共同点与镜像 target 那次一样：**改错了不报错**，容器照常起来、
只是永远不健康。配置层面没有人会主动去跑一次完整部署，所以写成断言。

检查项：

1. `env.example` 不含 `DATABASE_URL=`（拼连接串是编排文件的事；
   手写就会与 POSTGRES_PASSWORD 脱钩）；
2. `env.example` 里 `POSTGRES_PASSWORD` 有非空默认值，且 compose 的
   `DATABASE_URL` 默认值**嵌套引用**了它（而不是另一个字面密码）；
3. `env.example` 里 `REDIS_ENABLED=true`（compose 部署的硬要求）；
4. compose 里所有 `${VAR}` 都出现在 `env.example` 中（客户不用猜变量名）；
5. `env.example` 的每个 `KEY=` 都在 compose 里被用到，或是后端会读的
   通用配置 —— 反向检查「文档里的死变量」（如 PORT/HOST 在授权版里无效）；
6. DEPLOY.md 第 3 步真的包含两条 sed，且提到了这两个变量；
7. `env.example` 不含任何看起来像真密钥的值。

退出码 0 = 一致；1 = 有漂移（逐条打印）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / "env.example"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / "DEPLOY.md"


def active_assignments(text: str) -> dict[str, str]:
    """只取真正生效的 KEY=VALUE（跳过注释行与空值占位）"""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            out[key] = val.strip()
    return out


def check_database() -> list[str]:
    problems: list[str] = []
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    compose = COMPOSE_PROD.read_text(encoding="utf-8")

    # 1. 不得出现手写的 DATABASE_URL
    for raw in env_text.splitlines():
        line = raw.strip()
        if line.startswith("DATABASE_URL="):
            problems.append(
                "env.example 里出现了生效的 DATABASE_URL= —— 手写它就会与 "
                "POSTGRES_PASSWORD 脱钩（实测报 password authentication failed）。"
                "连接串交给 docker-compose.prod.yml 拼：它内部已经嵌套引用 "
                "POSTGRES_PASSWORD"
            )
            break

    # 2. compose 的 DATABASE_URL 默认值必须嵌套引用密码，而不是另一个字面密码
    m = re.search(r"DATABASE_URL:\s*\$\{DATABASE_URL:-(.*?)\}\s*$",
                  compose, re.MULTILINE)
    if not m:
        problems.append(
            "docker-compose.prod.yml 里找不到 DATABASE_URL 的默认值 —— "
            "客户删掉 env.example 的变量后就连不上库了"
        )
    elif "POSTGRES_PASSWORD" not in m.group(1):
        problems.append(
            "docker-compose.prod.yml 的 DATABASE_URL 默认值没有引用 "
            f"POSTGRES_PASSWORD（当前是 {m.group(1)!r}）—— "
            "必须用嵌套插值，否则改密码时两处会脱钩"
        )

    env_vals = active_assignments(env_text)
    if "POSTGRES_PASSWORD" not in env_vals:
        problems.append("env.example 里没有生效的 POSTGRES_PASSWORD")
    elif not env_vals["POSTGRES_PASSWORD"]:
        problems.append("env.example 的 POSTGRES_PASSWORD 是空值")
    return problems


def check_redis() -> list[str]:
    problems: list[str] = []
    env_vals = active_assignments(ENV_EXAMPLE.read_text(encoding="utf-8"))
    got = env_vals.get("REDIS_ENABLED")
    if got is None:
        problems.append(
            "env.example 里没有生效的 REDIS_ENABLED —— compose 默认 true，"
            "但客户很容易自己写成 false（实测会让 worker 拒绝启动、永远不 healthy）"
        )
    elif got.lower() != "true":
        problems.append(
            f"env.example 的 REDIS_ENABLED={got!r} —— compose 部署必须为 true："
            "worker 在 false 时直接拒绝启动，而健康检查硬断言 Redis 里有 worker 心跳"
        )
    return problems


def check_compose_vars_documented() -> list[str]:
    """compose 里引用的每个变量，env.example 都要有（客户不用猜名字）"""
    problems: list[str] = []
    compose = COMPOSE_PROD.read_text(encoding="utf-8")
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    used = set()
    for raw in compose.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        for m in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", line):
            used.add(m.group(1))

    for var in sorted(used):
        # env.example 里要么生效、要么以注释形式给出（KEY=... 或行中提到该名字）
        if re.search(rf"^\s*#?\s*{re.escape(var)}=", env_text, re.MULTILINE):
            continue
        if re.search(rf"^\s*#.*\b{re.escape(var)}\b", env_text, re.MULTILINE):
            continue
        problems.append(
            f"docker-compose.prod.yml 用了 ${{{var}}}，但 env.example 里既没有生效值"
            "也没有注释说明 —— 客户看到 compose 里出现一个陌生变量名会不知道是什么"
        )
    return problems


def check_no_dead_vars() -> list[str]:
    """反向检查：env.example 里授权版用不到的「死变量」"""
    problems: list[str] = []
    compose = COMPOSE_PROD.read_text(encoding="utf-8")
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")

    # 这些在授权版里完全不起作用（compose 内部固定或镜像内已定），
    # 留着会让客户以为改了有用
    dead = {
        "PORT": "对外端口是 AETRIX_PORT；这个是容器内部端口，compose 不读它",
        "HOST": "镜像内已固定 0.0.0.0，compose 不读它",
    }
    env_vals = active_assignments(env_text)
    for var, why in dead.items():
        if var in env_vals:
            problems.append(
                f"env.example 里生效的 {var}= 在授权版里完全不起作用（{why}）。"
                "写成注释并说明，否则客户改了以为生效、实际白改"
            )
    return problems


def check_deploy_doc() -> list[str]:
    problems: list[str] = []
    doc = DEPLOY.read_text(encoding="utf-8")

    if "s|^SECRET_KEY=" not in doc:
        problems.append("DEPLOY.md 第 3 步缺少生成 SECRET_KEY 的 sed")
    if "s|^POSTGRES_PASSWORD=" not in doc:
        problems.append("DEPLOY.md 第 3 步缺少改 POSTGRES_PASSWORD 的 sed")

    # 文档必须警告不要手改 DATABASE_URL（否则第 1 条防线没了）
    if "DATABASE_URL" not in doc:
        problems.append(
            "DEPLOY.md 全文没提 DATABASE_URL —— 客户很容易自己加一行，"
            "而那正是密码脱钩的起点"
        )
    # 必须覆盖 Redis 这个坑
    if "REDIS_ENABLED" not in doc:
        problems.append(
            "DEPLOY.md 没提 REDIS_ENABLED —— 客户看到 env.example 的 false "
            "会直接改，于是服务永远不健康"
        )
    return problems


def check_no_real_secrets() -> list[str]:
    """env.example 不该含看起来像真密钥的值"""
    problems: list[str] = []
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    suspicious = {
        "SECRET_KEY": r"SECRET_KEY=\S{20,}",
        "POSTGRES_PASSWORD": r"POSTGRES_PASSWORD=\S{20,}",
        "PAN115": r"PAN115_COOKIE=\S{20,}",
    }
    for name, pat in suspicious.items():
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            if re.search(pat, line):
                problems.append(f"env.example 里 {name} 看起来填了真值（发行包会带上它）")
                break
    return problems


def main() -> int:
    problems: list[str] = []
    for fn in (
        check_database,
        check_redis,
        check_compose_vars_documented,
        check_no_dead_vars,
        check_deploy_doc,
        check_no_real_secrets,
    ):
        try:
            problems.extend(fn())
        except FileNotFoundError as exc:
            problems.append(f"文件不存在：{exc.filename}")

    if problems:
        print("授权版环境变量契约不一致：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    env_vals = active_assignments(ENV_EXAMPLE.read_text(encoding="utf-8"))
    print("✅ 授权版环境变量契约一致：")
    print("   DATABASE_URL      不出现在 env.example（由 compose 按密码拼）")
    print(f"   POSTGRES_PASSWORD 有默认值，且被 compose 的连接串嵌套引用")
    print(f"   REDIS_ENABLED     ={env_vals['REDIS_ENABLED']}（worker 硬要求）")
    print("   PORT / HOST       已降为注释并标注「改了没用」")
    print("   DEPLOY.md         两条 sed + DATABASE_URL/REDIS_ENABLED 警告均在位")
    print("   发行包无真密钥")
    return 0


if __name__ == "__main__":
    sys.exit(main())
