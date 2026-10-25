#!/usr/bin/env bash
# Run from any directory: bash /opt/apps/resource-hub/update.sh [--force]
set -Eeuo pipefail
umask 077

cleanup() {
  if [[ -n "${update_tmp:-}" ]]; then
    rm -f -- "$update_tmp/Dockerfile" "$update_tmp/compose.yaml" \
      "$update_tmp/incoming" "$update_tmp/current"
    rmdir -- "$update_tmp" 2>/dev/null || true
  fi
}

main() {
  if [[ $# -gt 1 || ( $# -eq 1 && "$1" != '--force' ) ]]; then
    echo '用法：bash update.sh [--force]' >&2
    return 2
  fi
  force=${1:-}
  project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  cd -- "$project_root"
  for command in git docker flock mktemp sed cmp; do
    command -v "$command" >/dev/null || { echo "缺少命令：$command" >&2; return 1; }
  done
  docker compose version >/dev/null
  [[ -f backend/.env ]] || { echo '缺少 backend/.env，请先完成首次部署。' >&2; return 1; }
  [[ "$(git branch --show-current)" == main ]] || {
    echo '请先切换到 main 分支；脚本不会自动切换或覆盖工作区。' >&2; return 1;
  }
  cache_dir="$project_root/.cache/update"
  mkdir -p -- "$cache_dir"
  exec 9>"$cache_dir/lock"
  flock -n 9 || { echo '已有更新任务运行，本次跳过。'; return 0; }
  export GIT_TERMINAL_PROMPT=0
  update_tmp=$(mktemp -d /tmp/resource-hub-update.XXXXXX)
  trap cleanup EXIT

  echo '正在检查 GitHub main 分支…'
  git fetch origin main
  target_commit=$(git rev-parse refs/remotes/origin/main)
  git merge-base --is-ancestor HEAD "$target_commit" || {
    echo '本地分支与远程分支存在分歧，请先处理；当前应用未被更新。' >&2; return 1;
  }

  # First migration: manually uploaded files may become tracked files.
  # Only move matching files, preserving a backup before Git checks them out.
  override=backend/compose.pansou.yaml
  migration_paths=()
  migration_backups=()
  for migration_path in "$override" update.sh; do
    if [[ -f "$migration_path" ]] && ! git ls-files --error-unmatch "$migration_path" >/dev/null 2>&1 \
        && git cat-file -e "$target_commit:$migration_path" 2>/dev/null; then
      normalize='s/\r$//'
      if [[ "$migration_path" == "$override" ]]; then
        normalize+='; /^[[:space:]]*#/d; /^[[:space:]]*$/d'
      fi
      git show "$target_commit:$migration_path" | sed "$normalize" >"$update_tmp/incoming"
      sed "$normalize" "$migration_path" >"$update_tmp/current"
      cmp -s "$update_tmp/current" "$update_tmp/incoming" || {
        echo "本机 $migration_path 与远程内容不同，请先合并；脚本未覆盖它。" >&2; return 1;
      }
      migration_paths+=("$migration_path")
      migration_backups+=("$cache_dir/$(basename "$migration_path").$(date +%Y%m%d-%H%M%S).backup")
    fi
  done
  for index in "${!migration_paths[@]}"; do
    mv -- "${migration_paths[$index]}" "${migration_backups[$index]}"
  done
  if ! git merge --ff-only "$target_commit"; then
    for index in "${!migration_paths[@]}"; do
      [[ -e "${migration_paths[$index]}" ]] || cp -- "${migration_backups[$index]}" "${migration_paths[$index]}"
    done
    echo '代码拉取失败，请处理本地修改后重试；脚本不会强制覆盖代码。' >&2
    return 1
  fi

  if [[ "$force" != '--force' && -f "$cache_dir/deployed-commit" \
      && "$(cat "$cache_dir/deployed-commit")" == "$target_commit" ]]; then
    echo '当前版本已部署，无需更新。使用 --force 可重新构建。'
    return 0
  fi

  # Build a temporary Dockerfile to retain the working ECR image source,
  # without editing tracked files or requiring Docker daemon restarts.
  python_image=${RESOURCE_HUB_PYTHON_IMAGE:-public.ecr.aws/docker/library/python:3.12-slim}
  [[ "$python_image" =~ ^[a-zA-Z0-9./:@_-]+$ ]] || {
    echo 'RESOURCE_HUB_PYTHON_IMAGE 格式不正确。' >&2; return 1;
  }
  sed -E "s|^FROM (python:3\\.12-slim\|public\\.ecr\\.aws/docker/library/python:3\\.12-slim)[[:space:]]*$|FROM $python_image|" \
    backend/Dockerfile >"$update_tmp/Dockerfile"
  # The third file changes only the Dockerfile used for this build.
  printf 'services:\n  app:\n    build:\n      dockerfile: %s/Dockerfile\n' "$update_tmp" >"$update_tmp/compose.yaml"
  compose=(docker compose --project-directory "$project_root/backend"
    --env-file "$project_root/backend/.env" -f "$project_root/backend/compose.yaml")
  if [[ -f "$override" ]]; then
    compose+=(-f "$project_root/$override")
    docker network inspect resource-hub-upstream >/dev/null || {
      echo '缺少 resource-hub-upstream 网络，请先完成 PanSou 网络连接。' >&2; return 1;
    }
  fi
  compose+=(-f "$update_tmp/compose.yaml")
  "${compose[@]}" config --quiet
  echo '正在构建新版本，现有应用继续运行…'
  "${compose[@]}" build app
  echo '正在更新应用并等待健康检查…'
  if ! "${compose[@]}" up -d --no-build --no-deps --wait --wait-timeout 120 app; then
    echo '应用未通过启动检查，未标记部署成功。请查看 app 日志；修复后重新运行本脚本。' >&2
    return 1
  fi
  printf '%s\n' "$target_commit" >"$cache_dir/deployed-commit"
  echo "更新完成：$(git rev-parse --short HEAD)。网页、网页 API 和 MCP 已一起更新。"
}

# Keep the whole update in a parsed function: git may update this script itself.
main "$@"
