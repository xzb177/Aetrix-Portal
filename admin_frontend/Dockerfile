# RoyalBot Admin Frontend Dockerfile
# 多阶段构建：构建阶段 + Nginx 运行阶段

# ==================== 阶段1: 构建阶段 ====================
FROM node:22-alpine AS builder

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY package*.json ./

# 安装依赖
RUN npm ci --legacy-peer-deps

# 复制源代码
COPY . .

# 构建项目
RUN npm run build

# ==================== 阶段2: Nginx 运行阶段 ====================
FROM nginx:alpine

# 复制构建产物到 /admin 子目录
COPY --from=builder /app/dist /usr/share/nginx/html/admin

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 修复权限（nginx 用户已存在于镜像中）
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /run/nginx.pid && \
    chown nginx:nginx /run/nginx.pid

USER nginx

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:80/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
