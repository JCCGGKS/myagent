# myagent 全栈（前端 + 后端 + 依赖）一键管理
#
# 用法示例：
#   make up          # 构建并启动全栈（代码有改动时）
#   make up-fast     # 仅启动（镜像已存在、代码未改，更快）
#   make down        # 停止并移除容器（保留数据卷）
#   make restart     # 重启前后端
#   make logs        # 跟踪前后端日志
#   make build       # 仅重建镜像
#   make ps          # 查看服务状态
#
# 说明：
# - 后端代码 / 前端依赖均烤进镜像，改代码后务必用 `make up`（含 --build）。
# - 仅改 llm_config.docker.yml 配置：用 `make restart-app` 即可，无需重建。

COMPOSE := docker compose

.PHONY: help up up-fast down stop restart restart-app restart-frontend logs build ps status clean hints

help: ## 显示帮助
	@echo "可用目标："
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

hints: ## 启动后打印常用操作提示（由 up / up-fast 自动调用）
	@echo ""
	@echo "\033[32m✅ 全栈已启动\033[0m"
	@IP=$$(hostname -I 2>/dev/null | awk '{print $$1}'); \
	echo "  前端:"; \
	for u in "http://127.0.0.1:5173" "http://localhost:5173" "http://$$IP:5173"; do \
		printf '    \033]8;;%s\033\\%s\033]8;;\033\\\n' "$$u" "$$u"; \
	done; \
	echo "  后端 (前端经 /api 代理访问):"; \
	for u in "http://127.0.0.1:8000" "http://localhost:8000" "http://$$IP:8000"; do \
		printf '    \033]8;;%s\033\\%s\033]8;;\033\\\n' "$$u" "$$u"; \
	done; \
	echo "  （127.0.0.1 / localhost 用于本机；其他设备/远程访问请用上面的宿主机 IP）"
	@echo ""
	@echo "\033[36m常用操作：\033[0m"
	@echo "  查看状态          make ps"
	@echo "  跟踪前后端日志    make logs                    # 等价 docker compose logs -f app frontend"
	@echo "  只看后端日志      docker compose logs -f app --tail=50"
	@echo "  重启后端(改配置)  make restart-app             # 不重建镜像"
	@echo "  改代码后重启      make up                      # 含 --build 重建镜像"
	@echo "  停止全栈          make down"
	@echo "  进后端容器        docker compose exec app bash"
	@echo "  进 mysql          docker compose exec mysql mysql -uroot -p"
	@echo "  进 redis           docker compose exec redis redis-cli ping"
	@echo ""
	@echo "更多目标见 \033[36mmake help\033[0m"

up: ## 构建并启动全栈（代码有改动时用）
	$(COMPOSE) up -d --build
	$(MAKE) hints

up-fast: ## 仅启动全栈（镜像已存在、代码未改）
	$(COMPOSE) up -d
	$(MAKE) hints

down: ## 停止并移除容器（保留数据卷）
	$(COMPOSE) down

stop: ## 停止容器（保留容器，可 restart）
	$(COMPOSE) stop

restart: ## 重启前后端（重建镜像）
	$(COMPOSE) up -d --build app frontend

restart-app: ## 仅重启后端（配置改动后常用，不重建镜像）
	$(COMPOSE) restart app

restart-frontend: ## 仅重启前端（不重建镜像）
	$(COMPOSE) restart frontend

build: ## 仅重建所有镜像
	$(COMPOSE) build

logs: ## 跟踪前后端日志
	$(COMPOSE) logs -f app frontend

ps: status  ## 查看服务状态

status: ## 查看服务状态
	$(COMPOSE) ps

clean: ## 停止并移除容器 + 数据卷（会清空 mysql/redis/qdrant 数据）
	$(COMPOSE) down -v
