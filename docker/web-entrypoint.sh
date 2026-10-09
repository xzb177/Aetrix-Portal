#!/bin/sh
# 前端 nginx 容器启动钩子：把模板里的 ${BACKEND_HOST} 渲染成最终配置。
# 只替换 BACKEND_HOST 一个变量（nginx 自带的 $host/$uri/$remote_addr 等必须原样保留）。
# 未设置 BACKEND_HOST 时默认 aetrix-api:8000（本地/单机部署）。
set -e

export BACKEND_HOST="${BACKEND_HOST:-aetrix-api:8000}"

envsubst '${BACKEND_HOST}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf
