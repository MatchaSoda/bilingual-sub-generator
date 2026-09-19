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
#   ./docker-start.sh model      只确保 Whisper 模型已下载（启动时会自动做，这个是手动触发）
#   ./docker-start.sh export     打包 userdata/（key、cookie、频道、历史）用于迁移到别的机器
#   ./docker-start.sh import X   在新机器上导入上面打的包，然后 ./docker-start.sh 即可
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

# 容器以当前用户身份运行（见 docker-compose.yml 的 PUID/PGID），生成的文件属主是你而不是 root
export PUID="${PUID:-$(id -u)}" PGID="${PGID:-$(id -g)}"

# userdata 是否已经「齐活」——从别的机器迁过来的通常是。齐活就不必走向导，体检通过直接启动。
userdata_complete() {
    grep -qE '^GOOGLE_API_KEYS=.+' userdata/.env 2>/dev/null && [ -s userdata/cookies.txt ]
}

profile_args() {
    if grep -qE '^ENABLE_AUTOMATION=1' userdata/.env 2>/dev/null; then
        echo "--profile automation"
    fi
}

ensure_image() {
    if ! docker image inspect bilingual-sub-generator:latest >/dev/null 2>&1; then
        say "第一次运行，构建镜像（下载依赖约 2–3 GB，需要几分钟到十几分钟）…"
        if ! docker compose build; then
            warn "构建失败。最常见的原因是拉基础镜像或装依赖时网络抖动（DNS 污染会表现为 auth.docker.io 超时），10 秒后自动重试一次…"
            sleep 10
            docker compose build || die "还是失败。看上面最后的报错；如果是 'failed to fetch anonymous token' / 'i/o timeout'，先手工执行
   docker pull node:20-bookworm-slim && docker pull python:3.12-slim-bookworm
   多试几次拉下来后再运行本脚本。详见 docs/DOCKER.md §4。"
        fi
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
            if userdata_complete; then
                say "检测到 userdata/ 里已有 key 和 cookie（像是从别的机器迁过来的），先做一次体检而不是重走向导"
                if docker compose run --rm setup setup --check; then
                    date '+%Y-%m-%d %H:%M:%S (check passed, wizard skipped)' > userdata/.setup-done
                    say "体检通过，跳过向导"
                else
                    warn "体检没全过（多半是代理地址在这台机器上不对），进向导修一下；已有的 key / cookie / 频道都会保留"
                    run_setup
                fi
            else
                warn "还没做过首次设置，先进向导。"
                run_setup
            fi
        fi
        # 模型不在就先补下（在的话两秒无感）。失败不阻塞启动：第一次任务时还会再试，只是要多等。
        docker compose run --rm setup setup --download-model || warn "模型没下好，第一次处理视频时会自动重试；也可稍后 ./docker-start.sh model"
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
    model)
        ensure_image
        docker compose run --rm setup setup --download-model "${@:2}"
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
    export)
        # 不带 userdata/data/（生成好的视频，可能很大）和 .setup-done（新机器要重新体检）
        out="${2:-bilingual-sub-userdata-$(date +%Y%m%d-%H%M).tar.gz}"
        tar czf "$out" --exclude='userdata/data' --exclude='userdata/.setup-done' --exclude='userdata/.env.bak-*' \
            --exclude='userdata/history.lock' userdata
        chmod 600 "$out"
        say "已导出到 ${out}（含 key / cookie / B 站登录 / 频道配置 / history / 起点水位；不含生成的视频）"
        cat <<EOT
   到新机器上：
     git clone <本仓库> && cd bilingual-sub-generator
     ./docker-start.sh import ${out}
     ./docker-start.sh
   注意：包里有登录凭据，传完就删。旧机器上的服务要在新机器跑通后再停，
   停之前如果两边都在跑自动搬运会重复投稿——导入时会自动把 ENABLE_AUTOMATION 置 0，确认后再开。
EOT
        ;;
    import)
        archive="${2:-}"
        [ -n "$archive" ] && [ -f "$archive" ] || die "用法: ./docker-start.sh import <export 打出来的 .tar.gz>"
        if userdata_complete && [ "${3:-}" != "--force" ]; then
            die "userdata/ 里已经有 key 和 cookie 了，不覆盖。确定要覆盖就加 --force：./docker-start.sh import $archive --force"
        fi
        tar xzf "$archive"
        rm -f userdata/.setup-done
        # 防止新旧两台机器同时投稿：先关掉，用户确认旧机停了再 ./docker-start.sh setup 打开
        if grep -qE '^ENABLE_AUTOMATION=1' userdata/.env 2>/dev/null; then
            sed -i.bak -e 's/^ENABLE_AUTOMATION=1/ENABLE_AUTOMATION=0/' userdata/.env && rm -f userdata/.env.bak
            warn "已把 ENABLE_AUTOMATION 置 0：等旧机器的服务停掉后，运行 ./docker-start.sh setup 到第 4 步再打开"
        fi
        chmod 644 userdata/*.json 2>/dev/null || true
        chmod 600 userdata/.env userdata/cookies.txt userdata/cookies.json 2>/dev/null || true
        say "已导入。接下来运行 ./docker-start.sh —— 它会先体检（代理地址可能要按这台机器改），通过就直接启动"
        ;;
    *)
        sed -n '2,15p' "$0"
        ;;
esac
