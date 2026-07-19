# 前端开发容器：Vue3 + Vite 开发服务器（npm run dev，带 HMR）。
# 与后端 Dockerfile 同约定：依赖烤进镜像，源码以卷挂入实现热更新。
FROM node:20-alpine

WORKDIR /app

# 先装依赖（利用层缓存：package.json 不变则不重装）
COPY package*.json ./
RUN npm install

# 再拷源码（node_modules / dist 由 .dockerignore 排除）
COPY . .

EXPOSE 5173

# host 0.0.0.0 让容器外（宿主机浏览器）可访问；端口与 vite.config.ts 一致。
# 代理目标由环境变量 VITE_PROXY_TARGET 决定（docker 内指向 app:8000）。
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
