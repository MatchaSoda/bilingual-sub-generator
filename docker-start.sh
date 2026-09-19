#!/usr/bin/env bash
# 一键启动（Docker 版）。Linux / macOS / Windows(WSL 或 Git Bash) 通用。
#
#   ./docker-start.sh            首次自动进入设置向导，之后直接启动
#   ./docker-start.sh setup      重新跑设置向导（换 cookie、改代理、加频道…）
#   ./docker-start.sh logs       跟踪日志
#   ./docker-start.sh stop       停止
#   ./docker-start.sh update     拉最新代码并重建镜像（yt-dlp 过期时用）
#   ./docker-start.sh shell      进容器排查
#   ./docker-start.sh check      不交互地体检当前配置
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { echo -e "${GREEN}▶ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
die()  { echo -e "${RED}✖ $*${NC}" >&2; exit 1; }

# ---------- 0. Docker 在不在 ----------
if ! command -v docker >/dev/null 2>&1; then
    die "没找到 docker 命令。请先安装 Docker Desktop（Windows/macOS）或 Docker Engine（Linux）：https://docs.docker.com/get-docker/
   Windows 用户：安装 Docker Desktop 后，在 WSL 终端或 Git Bash 里重新运行本脚本。"
fi
if ! docker info >/dev/null 2>&1; then
    die "docker 装了但没在运行（或当前用户没权限）。请启动 Docker Desktop；Linux 上试试 sudo usermod -aG docker \$USER 后重新登录。"
fi
if ! docker compose version >/dev/null 2>&1; then
    die "缺少 docker compose 插件（v2）。Docker Desktop 自带；Linux 请安装 docker-compose-plugin。"
fi

# ---------- 1. 用户数据目录与占位文件 ----------
# compose 的 env_file 要求文件存在；cookies.txt 以空文件占位（程序把空文件当不存在）
mkdir -p userdata data
[ -f userdata/.env ] || cp docker/env.example userdata/.env
[ -e userdata/cookies.txt ] || : > userdata/cookies.txt
chmod 600 userdata/.env userdata/cookies.txt 2>/dev/null || true

profile_args() {
    if grep -qE '^ENABLE_AUTOMATION=1' userdata/.env 2>/dev/null; then
        echo "--profile automation"
    fi
}

ensure_image() {
    if ! docker image inspect bilingual-sub-generator:latest >/dev/null 2>&1; then
        say "第一次运行，构建镜像（下载依赖约 2–3 GB，需要几分钟到十几分钟）…"
        docker compose build
    fi
}

run_setup() {
    ensure_image
    say "进入设置向导"
    docker compose run --rm setup
}

cmd="${1:-start}"
case "$cmd" in
    start)
        ensure_image
        if [ ! -f userdata/.setup-done ]; then
            warn "还没做过首次设置，先进向导。"
            run_setup
        fi
        # shellcheck disable=SC2046
        say "启动服务"
        docker compose $(profile_args) up -d --remove-orphans
        echo
        say "Web 界面: http://localhost:8501"
        if grep -qE '^ENABLE_AUTOMATION=1' userdata/.env; then
            say "自动搬运已启动，看日志: ./docker-start.sh logs"
        else
            say "自动搬运未启用（只有 Web 界面）。要开启请运行 ./docker-start.sh setup"
        fi
        ;;
    setup)
        run_setup
        # 向导可能改了 ENABLE_AUTOMATION / 代理，重新 up 让新配置生效
        # shellcheck disable=SC2046
        if docker compose ps -q web 2>/dev/null | grep -q .; then
            say "重新加载服务配置"
            docker compose $(profile_args) up -d --remove-orphans
        else
            say "向导完成。运行 ./docker-start.sh 启动服务。"
        fi
        ;;
    check)
        ensure_image
        docker compose run --rm setup setup --check
        ;;
    logs)
        # shellcheck disable=SC2046
        docker compose $(profile_args) logs -f --tail=200 "${@:2}"
        ;;
    stop)
        docker compose --profile automation down
        say "已停止（数据都在 ./userdata 和 ./data，不会丢）"
        ;;
    update)
        if [ -d .git ]; then
            say "拉取最新代码"; git pull --ff-only || warn "git pull 失败，只重建镜像"
        fi
        say "重建镜像"
        docker compose build --pull
        # shellcheck disable=SC2046
        docker compose $(profile_args) up -d --remove-orphans
        ;;
    shell)
        ensure_image
        docker compose run --rm --entrypoint bash setup
        ;;
    *)
        sed -n '2,12p' "$0"
        ;;
esac
