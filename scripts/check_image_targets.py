#!/usr/bin/env python3
"""发行镜像 target 门禁：谁用带 scripts/ 的变体，谁必须用精简变体

背景（v2.42.10）：`Dockerfile.backend` 从单 stage 改成 base / with-scripts / runtime
三个 stage，运维脚本（造管理员、迁移库、冒烟）进了一个专门的 with-scripts target。
这样「客户镜像不带测试脚本」与「自建部署能 exec 跑脚本」两个需求可以共存。

但它们共存的方式是**一份配置里两个天壤之别的产物**，靠人记住就迟早出事：

- `docker build` 不带 `--target` 时构建**最后一个** stage。哪天有人为了图省事把
  `FROM base AS runtime` 挪到前面、或者在末尾加一个 stage，发布流水线就会
  **静默**构建出带 scripts/ 的镜像推到 ghcr.io —— 客户随时可能拉，且 ghcr 的
  latest 被覆盖后没法悄悄撤回。
- 反过来，谁把 `docker-compose.yml` 里那个 `target: with-scripts` 删掉，自建部署
  的运维脚本就静默消失（镜像正常起来，只是 exec 进去发现目录是空的）。

这两个方向都不会报错，所以本脚本把不变量写成断言，让 CI 挡住。

检查项：

1. `Dockerfile.backend` 的最后一个 stage 是 `runtime`，且它不带任何 COPY
   （默认值必须是精简版）；
2. `runtime` 之前存在 `with-scripts` stage，且它 COPY 了 scripts/；
3. `publish-images.yml` 构建后端镜像时**显式**写 `--target runtime`
   （不依赖默认值）；
4. `docker-compose.yml` 的 `aetrix-api` 用 `target: with-scripts`；
5. `docker-compose.prod.yml` 里**没有** build:、**没有** target —— 客户版只
   允许拉 ghcr 镜像，出现任何一个都说明编排被污染了；
6. `.dockerignore` 没有排除 `scripts/`（排除了的话 with-scripts 那行 COPY 会
   **静默产出空目录**：不报错、构建绿、exec 进去才发现脚本一个都没有）。

退出码 0 = 全部一致；1 = 有漂移（逐条打印）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile.backend"
DOCKERIGNORE = ROOT / ".dockerignore"
PUBLISH_WF = ROOT / ".github" / "workflows" / "publish-images.yml"
COMPOSE_DEV = ROOT / "docker-compose.yml"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"

LEAN_TARGET = "runtime"
OPS_TARGET = "with-scripts"
BASE_TARGET = "base"

FROM_RE = re.compile(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", re.IGNORECASE)
COPY_RE = re.compile(r"^COPY\s+(?:--\S+\s+)*(.+)$", re.IGNORECASE)


def parse_stages(text: str) -> list[tuple[str, str, list[str]]]:
    """把 Dockerfile 拆成 [(基础镜像, 阶段名, 该阶段的指令行), ...]

    只按 stage 边界切，不解析指令语义 —— 本门禁要的就是「哪个 stage 里有哪几行
    COPY」这个粗粒度事实，用完整的 Dockerfile 解析器反而会被 ARG/ENV 展开之类
    的细节绊住。
    """
    stages: list[tuple[str, str, list[str]]] = []
    base = alias = ""
    body: list[str] = []
    in_docstring = False

    for raw in text.splitlines():
        line = raw.strip()
        # 跳过注释与文档字符串（""" 包裹的整块说明），它们里出现的 FROM/COPY
        # 只是散文，解析了反而得到一堆假 stage。
        if in_docstring:
            if line.endswith('"""'):
                in_docstring = False
            continue
        if line.startswith('"""'):
            if not (line.endswith('"""') and len(line) > 3):
                in_docstring = True
            continue
        if not line or line.startswith("#"):
            continue

        m = FROM_RE.match(line)
        if m:
            if base or alias:
                stages.append((base, alias, body))
            base, alias, body = m.group(1), (m.group(2) or "").lower(), []
            continue
        body.append(line)

    if base or alias:
        stages.append((base, alias, body))
    return stages


def stage_copies(body: list[str]) -> list[str]:
    out = []
    for line in body:
        m = COPY_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def check_stages() -> list[str]:
    problems: list[str] = []
    stages = parse_stages(DOCKERFILE.read_text(encoding="utf-8"))
    names = [name for _, name, _ in stages]

    if not stages:
        return [f"{DOCKERFILE.name} 里没解析出任何 stage"]

    if BASE_TARGET not in names:
        problems.append(f"{DOCKERFILE.name} 缺少 base stage")
    if OPS_TARGET not in names:
        problems.append(
            f"{DOCKERFILE.name} 缺少 {OPS_TARGET} stage —— 自建部署就没有运维脚本可跑了"
        )
    if LEAN_TARGET not in names:
        problems.append(
            f"{DOCKERFILE.name} 缺少 {LEAN_TARGET} stage —— 发行镜像没有明确名字，"
            "发布流水线的 --target 会指向不存在的 stage"
        )

    # 1. 默认产物必须是精简版：最后一个 stage 名为 runtime 且不带 COPY。
    last_name = names[-1]
    if last_name != LEAN_TARGET:
        problems.append(
            f"默认构建的是最后一个 stage，而它是 {last_name!r} 而不是 {LEAN_TARGET!r}。"
            "不带 --target 的 docker build 会构建它 —— 客户镜像必须始终是精简版。"
            f"（当前 stage 顺序：{' → '.join(n or '<匿名>' for n in names)}）"
        )
    for copies in stage_copies(stages[-1][2]):
        problems.append(
            f"{LEAN_TARGET} stage 里不允许出现 COPY（实际是 `COPY {copies}`）。"
            "它是发行镜像的内容，新增文件请加到 base；"
            "要带 scripts/ 的是 with-scripts 那个 stage。"
        )

    # 2. with-scripts 必须真的 COPY 了 scripts/
    for i, (_, name, body) in enumerate(stages):
        if name != OPS_TARGET:
            continue
        copies = " ".join(stage_copies(body))
        if "scripts/" not in copies:
            problems.append(
                f"{OPS_TARGET} stage 里没有 COPY scripts/ —— 该 target 会构建成"
                "和 base 完全一样的镜像，运维脚本等于没加"
            )
        if stages[i][0] != BASE_TARGET:
            problems.append(
                f"{OPS_TARGET} 应该 FROM {BASE_TARGET}（当前 FROM {stages[i][0]}）"
            )
        break

    # 只有 with-scripts 能碰 scripts/：确认白名单 stage 一个都没拷它。
    for base_img, name, body in stages:
        if name == OPS_TARGET:
            continue
        for copies in stage_copies(body):
            if "scripts/" in copies:
                problems.append(
                    f"stage {name or '<匿名>'} 里出现了 `COPY {copies}` ——"
                    "scripts/ 只允许出现在 with-scripts stage，"
                    "否则它会顺带流进发行镜像"
                )
    return problems


def check_publish_workflow() -> list[str]:
    text = PUBLISH_WF.read_text(encoding="utf-8")
    problems: list[str] = []

    # shell 续行（\ 结尾）先接成一行，后面才好按「一条命令」为单位切。
    joined = text.replace("\\\n", " ")
    lines = joined.splitlines()

    # 切法：以 docker build 开头，往后吃到**空行或下一个 step** 为止 —— 也就是
    # 这条命令自己的跨度。
    #
    # 不要写成「往后找 Dockerfile.backend 出现为止」：那会把下一条 docker build
    # 之后的注释/自检一并吞进来（自检里提到 Dockerfile.backend 是完全正常的），
    # 于是前端那条命令被判成后端命令，得到一堆假的门禁失败。
    backend_builds: list[str] = []
    for idx, line in enumerate(lines):
        if "docker build" not in line or line.lstrip().startswith("#"):
            continue
        block = [line]
        for nxt in lines[idx + 1:]:
            if not nxt.strip() or nxt.lstrip().startswith(("- name:", "#")):
                break
            block.append(nxt)
        cmd = "\n".join(block)
        if "-f Dockerfile.backend" in cmd:
            backend_builds.append(cmd)

    if not backend_builds:
        return ["publish-images.yml 里找不到构建 Dockerfile.backend 的 docker build 命令"]

    for cmd in backend_builds:
        if f"--target {LEAN_TARGET}" not in cmd:
            problems.append(
                "publish-images.yml 构建后端镜像时没有显式写 "
                f"`--target {LEAN_TARGET}` —— 不能依赖默认值："
                "stage 顺序一变就会静默推出带 scripts/ 的镜像，而 ghcr 的 latest "
                "被覆盖后撤不回来"
            )
        # 只看命令行本身（已剔除注释行），否则本函数上方的说明注释会把自己判死
        code = "\n".join(
            l for l in cmd.splitlines() if not l.lstrip().startswith("#")
        )
        if OPS_TARGET in code:
            problems.append(
                f"publish-images.yml 的发布命令里出现了 {OPS_TARGET} —— "
                "运维脚本镜像绝不能推到 ghcr.io"
            )
    return problems


def _service_block(text: str, service: str) -> str:
    """取 `\\n  <service>:` 到下一个同级服务之间的正文"""
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    base_indent = None
    for line in lines:
        m = re.match(r"^(\s+)([A-Za-z0-9_.-]+):\s*$", line)
        if m and not inside:
            if m.group(2) == service:
                inside = True
                base_indent = len(m.group(1))
                continue
        elif m and inside and len(m.group(1)) <= (base_indent or 0):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


def check_compose() -> list[str]:
    problems: list[str] = []

    dev = COMPOSE_DEV.read_text(encoding="utf-8")
    api = _service_block(dev, "aetrix-api")
    if not api:
        problems.append("docker-compose.yml 里找不到 aetrix-api 服务")
    else:
        if f"target: {OPS_TARGET}" not in api:
            problems.append(
                f"docker-compose.yml 的 aetrix-api 没有 `target: {OPS_TARGET}` —— "
                "自建部署的 docker exec 运维脚本会静默消失"
            )
        if "Dockerfile.backend" not in api:
            problems.append("docker-compose.yml 的 aetrix-api 不再构建 Dockerfile.backend")

    prod = COMPOSE_PROD.read_text(encoding="utf-8")
    # build: 只可能出现在服务层，volumes 层不会写它，全文扫即可
    if re.search(r"^\s*build\s*:", prod, re.MULTILINE):
        problems.append(
            "docker-compose.prod.yml 里出现了 build: —— 客户版只允许拉 ghcr 镜像，"
            "出现 build: 就意味着客户要拿源码才能起服务"
        )
    if re.search(rf"^\s*target\s*:\s*{OPS_TARGET}", prod, re.MULTILINE):
        problems.append(
            f"docker-compose.prod.yml 里出现了 target: {OPS_TARGET} —— "
            "客户编排不应指向自建用的运维变体"
        )
    for svc in re.findall(r"ghcr\.io/xzb177/([a-z-]+)", prod):
        if svc not in ("aetrix-api", "aetrix-web"):
            problems.append(f"docker-compose.prod.yml 引用了预期外的镜像：{svc}")
    return problems


def check_dockerignore() -> list[str]:
    problems: list[str] = []
    for raw in DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pat = line.rstrip("/")
        if pat == "scripts" or line == "scripts/":
            problems.append(
                ".dockerignore 排除了 scripts/ —— with-scripts 那行 COPY 会"
                "**静默产出空目录**：不报错、构建绿、exec 进去才发现一个脚本都没有。"
                ".dockerignore 不是发行边界（Dockerfile 白名单才是），这里排除纯属有害"
            )
            break
    return problems


def main() -> int:
    problems: list[str] = []
    for fn in (check_stages, check_publish_workflow, check_compose, check_dockerignore):
        try:
            problems.extend(fn())
        except FileNotFoundError as exc:
            problems.append(f"文件不存在：{exc.filename}")

    if problems:
        print("镜像 target 契约不一致：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("✅ 镜像 target 契约一致：")
    print(f"   Dockerfile.backend   base → {OPS_TARGET}（自建，带 scripts/）→ "
          f"{LEAN_TARGET}（默认 = 发行，无 scripts/）")
    print(f"   publish-images.yml   显式 --target {LEAN_TARGET}")
    print(f"   docker-compose.yml   aetrix-api target: {OPS_TARGET}")
    print("   compose.prod.yml     只有 ghcr 镜像，无 build: / 无 target")
    return 0


if __name__ == "__main__":
    sys.exit(main())
