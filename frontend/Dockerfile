# ── 阶段 1：构建前端静态产物 ────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# 仅复制依赖清单，利用 Docker 层缓存
COPY package.json package-lock.json ./
RUN npm ci

# 复制源码（.dockerignore 已排除 node_modules/dist，不会覆盖已装依赖）
COPY . .

# 构建期可注入后端绝对地址；留空 = 同源相对路径（由 nginx 反代）
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

# ── 阶段 2：nginx 托管静态产物 + 反代后端 ──────────────────────────────────
FROM nginx:1.27-alpine

# 官方镜像 entrypoint 会对 /etc/nginx/templates/*.template 做 envsubst（仅替换已定义环境变量）
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

# 后端地址（运行期注入；默认指向宿主机发布的后端端口）
ENV BACKEND_URL=http://host.docker.internal:8080

EXPOSE 80
