#!/usr/bin/env bash
# 一键停止并删除 myagent 项目依赖的 docker 容器
#
# 用法:
#   ./scripts/docker-down.sh            # 停止并删除核心容器 (mysql/redis/qdrant)，保留数据卷
#   ./scripts/docker-down.sh -v         # 同时删除数据卷 (慎用：mysql/redis/qdrant 数据将清空)
#   ./scripts/docker-down.sh --all      # 连可观测容器 (prometheus/grafana) 一起停止删除
#   ./scripts/docker-down.sh --all -v   # 全部容器 + 全部数据卷一起删除
#   ./scripts/docker-down.sh -h         # 查看帮助
#
# 说明:
#   核心基础设施 mysql/redis/qdrant 由后端运行时依赖；脚本默认只删除这些容器，
#   不影响 prometheus/grafana 可观测栈。加 -v 会删除匿名/命名数据卷，数据不可恢复。

set -euo pipefail

# 切到仓库根目录（脚本位于 <root>/scripts/）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

REMOVE_VOLUMES=false
INCLUDE_OBS=false

print_help() {
  sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--volumes) REMOVE_VOLUMES=true; shift ;;
    --all)        INCLUDE_OBS=true; shift ;;
    -h|--help)    print_help; exit 0 ;;
    *) echo "未知参数: $1"; print_help; exit 1 ;;
  esac
done

# 核心服务（后端运行时依赖）
SERVICES=(mysql redis qdrant app)
if [[ "${INCLUDE_OBS}" == true ]]; then
  SERVICES+=(prometheus grafana)
fi

echo "==> 当前目录: ${ROOT_DIR}"
echo "==> 将停止并删除容器: ${SERVICES[*]}"
if [[ "${REMOVE_VOLUMES}" == true ]]; then
  echo "==> 警告: 将同时删除数据卷 (mysql/redis/qdrant/prometheus/grafana 数据将被清空)"
fi

# 若 compose 文件存在，优先用 docker compose 精准管理这些服务
if [[ -f "docker-compose.yml" ]]; then
  CMD=(docker compose stop "${SERVICES[@]}")
  echo "==> 执行: ${CMD[*]}"
  "${CMD[@]}"

  CMD=(docker compose rm -f -s "${SERVICES[@]}")
  echo "==> 执行: ${CMD[*]}"
  "${CMD[@]}"

  if [[ "${REMOVE_VOLUMES}" == true ]]; then
    # 仅删除这些服务绑定的命名卷
    for vol in mysql_data redis_data qdrant_data prometheus_data grafana_data; do
      if docker volume inspect "${vol}" >/dev/null 2>&1; then
        docker volume rm "${vol}" >/dev/null 2>&1 && echo "==> 已删除数据卷: ${vol}" || echo "==> 跳过数据卷(占用中): ${vol}"
      fi
    done
  fi
else
  echo "==> 未找到 docker-compose.yml，回退到按容器名删除"
  for name in myagent-mysql myagent-redis myagent-qdrant myagent-prometheus myagent-grafana; do
    if docker ps -a --format '{{.Names}}' | grep -qx "${name}"; then
      docker rm -f "${name}" >/dev/null 2>&1 && echo "==> 已删除容器: ${name}"
    fi
  done
fi

echo "==> 完成。"
