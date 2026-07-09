#!/usr/bin/env bash
# 建表脚本
#
# 默认：在宿主机执行，但把表建到 docker 容器内的 MySQL（通过 docker exec，
# 这样即使容器端口未映射到宿主机也能建表）。
# 也可加 --host 参数改用宿主机 mysql 客户端直连（读配置里的 mysql 段）。
#
# 环境变量覆盖：
#   CONTAINER    MySQL 容器名（默认 myagent-mysql）
#   MYSQL_ROOT_PASSWORD  容器内 root 密码（默认 root，与 docker-compose 一致）
#   APP_ENV      配置环境（仅 --host 模式读取 mysql 段，默认 test）

set -euo pipefail

APP_ENV="${APP_ENV:-test}"
CONTAINER="${CONTAINER:-myagent-mysql}"
MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD:-root}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_FILE="$ROOT_DIR/config/llm_config.${APP_ENV}.yml"

MODE="docker"
if [ "${1:-}" = "--host" ]; then
  MODE="host"
  shift || true
fi

run_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "未找到 docker 命令，无法使用 docker 模式" >&2
    exit 1
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "容器 $CONTAINER 未运行，请先启动：docker compose up -d mysql" >&2
    exit 1
  fi

  echo "==> 在容器 $CONTAINER 内执行 01_users.sql（库 myagent，用户 root）"
  docker exec -i "$CONTAINER" \
    mysql -uroot -p"$MYSQL_ROOT_PASSWORD" myagent < "$SCRIPT_DIR/01_users.sql"

  echo "==> 完成。可选种子："
  echo "    docker exec -i $CONTAINER mysql -uroot -p'$MYSQL_ROOT_PASSWORD' myagent < $SCRIPT_DIR/02_init.sql"
}

run_host() {
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "配置文件不存在: $CONFIG_FILE" >&2
    exit 1
  fi

  # 用 python 解析 mysql 段
  mapfile -t DB < <(python - "$CONFIG_FILE" <<'PY'
import sys
from pathlib import Path
try:
    import yaml
except ImportError:
    print("需要 PyYAML：pip install PyYAML", file=sys.stderr); sys.exit(2)
data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
cfg = data.get("mysql", {})
for key in ("host", "port", "database", "user", "password"):
    print(str(cfg.get(key, "")))
PY
)
  HOST="${DB[0]}"; PORT="${DB[1]}"; DATABASE="${DB[2]}"; USER="${DB[3]}"; PASS="${DB[4]}"

  if [ -z "$HOST" ] || [ -z "$DATABASE" ]; then
    echo "mysql 配置缺失（host/database 为空）" >&2
    exit 1
  fi

  echo "==> 对 ${USER}@${HOST}:${PORT}/${DATABASE} 执行 01_users.sql"
  MYSQL_PWD="$PASS" mysql -h"$HOST" -P"$PORT" -u"$USER" "$DATABASE" < "$SCRIPT_DIR/01_users.sql"

  echo "==> 完成。可选种子：mysql ... < 02_init.sql"
}

if [ "$MODE" = "docker" ]; then
  run_docker
else
  run_host
fi
