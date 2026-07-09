#!/usr/bin/env bash
# 建表脚本：从 config/llm_config.{APP_ENV}.yml 读取 mysql 段并执行 01_users.sql
set -euo pipefail

APP_ENV="${APP_ENV:-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_FILE="$ROOT_DIR/config/llm_config.${APP_ENV}.yml"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "配置文件不存在: $CONFIG_FILE" >&2
  exit 1
fi

# 用 python 解析 mysql 段
read_db() {
  python - "$CONFIG_FILE" <<'PY'
import sys, os
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
}

mapfile -t DB < <(read_db)
HOST="${DB[0]}"; PORT="${DB[1]}"; DATABASE="${DB[2]}"; USER="${DB[3]}"; PASS="${DB[4]}"

if [ -z "$HOST" ] || [ -z "$DATABASE" ]; then
  echo "mysql 配置缺失（host/database 为空）" >&2
  exit 1
fi

echo "==> 对 ${USER}@${HOST}:${PORT}/${DATABASE} 执行 01_users.sql"
MYSQL_PWD="$PASS" mysql -h"$HOST" -P"$PORT" -u"$USER" "$DATABASE" < "$SCRIPT_DIR/01_users.sql"

echo "==> 完成。可选种子：mysql ... < 02_init.sql"
