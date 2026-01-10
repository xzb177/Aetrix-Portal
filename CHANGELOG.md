# 更新日志 (Changelog)

所有项目重要更改都将记录在此文件中。

## [2025-01-10]

### 新增 (Added)
- **一键部署脚本** (`deploy.sh`)
  - 支持 `--build` 强制重新构建镜像
  - 支持 `--no-cache` 构建时不使用缓存
  - 支持 `--backend` 仅部署后端服务
  - 支持 `--frontend` 仅部署前端服务
  - 支持 `--bot` 仅部署 Telegram Bot
  - 支持 `--rollback` 回滚到上一版本
  - 支持 `--status` 显示服务状态
  - 支持 `--logs` 显示服务日志
  - 支持 `--update` 更新代码并部署
  - 自动环境检查（Docker、Docker Compose、.env 文件）
  - 健康检查功能（本地 + 外部）
  - 旧镜像自动清理

### 功能特性
- 彩色日志输出（INFO/SUCCESS/WARNING/ERROR）
- 服务健康状态检测
- Git 代码自动更新
- 容器状态监控
- 完整的帮助文档

### 使用示例
```bash
./deploy.sh              # 部署所有服务
./deploy.sh --build      # 强制重新构建并部署
./deploy.sh --backend    # 仅部署后端服务
./deploy.sh --update     # 更新代码并部署
./deploy.sh --rollback   # 回滚到上一版本
```

---

## 之前版本

### [初始版本]
- RoyalBot Emby Portal 基础部署配置
- Docker Compose 配置
- Nginx 反向代理配置
- 基础环境变量模板
