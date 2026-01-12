# ==================== 构建阶段 ====================
FROM node:22-alpine AS builder

WORKDIR /app

# 复制 package 文件
COPY package*.json ./

# 安装依赖
RUN npm ci --legacy-peer-deps

# 复制源代码
COPY . .

# 构建生产版本（设置 NODE_ENV=production，跳过类型检查）
ENV NODE_ENV=production
RUN npm run build-only

# ==================== 生产阶段 - 使用 nginx + Brotli ====================
FROM nginx:alpine

# 安装 Brotli 压缩工具
RUN apk add --no-cache brotli

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 创建 Brotli 压缩脚本（使用正确的参数格式）
RUN echo '#!/bin/sh' > /compress.sh && \
    echo 'find /usr/share/nginx/html -type f \( -name "*.js" -o -name "*.css" -o -name "*.html" -o -name "*.svg" -o -name "*.json" \) -exec brotli -q 6 -f {} +' >> /compress.sh && \
    chmod +x /compress.sh && \
    /compress.sh && \
    rm /compress.sh

# 设置权限
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /run/nginx.pid && \
    chown nginx:nginx /run/nginx.pid

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
