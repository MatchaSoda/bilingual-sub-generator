#!/usr/bin/env bash
# 迁移用户数据（key、cookie、B 站登录、频道配置、history、起点水位）到另一台机器。
# 裸机和 Docker 两种部署通用，四个方向都行：裸机↔裸机、裸机↔Docker、Docker↔Docker。
#
#   scripts/migrate.sh export [包名] [--from bare|docker]
#   scripts/migrate.sh import <包> [--to bare|docker] [--force]
#
# 包的格式固定是 userdata/ 目录结构（和 Docker 部署的 userdata/ 一致），所以老版本
# ./docker-start.sh export 打的包也能导入。部署方式不传就自动判断，判断依据会打印出来。
# 文件在两种部署下的位置见 docs/DOCKER.md §3.5。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { echo -e "${GREEN}▶ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
die()  { echo -e "${RED}✖ $*${NC}" >&2; exit 1; }

# 只迁这几个文件。生成的视频、下载缓存、锁文件、向导完成标记都不带。
FILES=".env cookies.txt cookies.json config.json history.json state.json"
SECRET_FILES=".env cookies.txt cookies.json"

# 某个文件在某种部署下的路径
path_of() {
    local layout="$1" name="$2"
    if [ "$layout" = docker ]; then
        echo "userdata/$name"
    else
        case "$name" in
            .env|cookies.txt) echo "$name" ;;
            *) echo "automation/$name" ;;
        esac
    fi
}

# 这种部署下有没有用户数据（空的占位文件不算）
has_state() {
    local layout="$1"
    grep -qE '^GOOGLE_API_KEYS=.+' "$(path_of "$layout" .env)" 2>/dev/null && return 0
    [ -s "$(path_of "$layout" cookies.txt)" ] && return 0
    local f
    for f in cookies.json config.json history.json; do
        [ -s "$(path_of "$layout" "$f")" ] && return 0
    done
    return 1
}

# 自动搬运是不是正在跑：跑着的时候 history 还会变，导出的是旧的
mover_running() {
    local layout="$1"
    if [ "$layout" = docker ]; then
        command -v docker >/dev/null 2>&1 && docker compose ps -q mover 2>/dev/null | grep -q .
    else
        command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet bili-mover 2>/dev/null
    fi
}

# 改 .env 里代理变量的主机部分。容器里 127.0.0.1 是容器自己，宿主机要写 host.docker.internal；反过来同理。
rewrite_proxy_host() {
    local file="$1" from="$2" to="$3"
    [ -f "$file" ] || return 0
    if grep -qE "^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|GEMINI_PROXY)=.*//${from}[:/]" "$file"; then
        sed -i.bak -E "/^(HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|GEMINI_PROXY)=/s#//${from}([:/])#//${to}\1#g" "$file"
        rm -f "$file.bak"
        return 0
    fi
    return 1
}

STAGE=""
make_stage() {
    STAGE=$(mktemp -d)
    trap 'rm -rf "$STAGE"' EXIT
}

parse_layout() {
    case "$1" in
        bare|docker) echo "$1" ;;
        *) die "部署方式只能是 bare 或 docker，收到：$1" ;;
    esac
}

cmd_export() {
    local out="" from=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --from) from=$(parse_layout "${2:-}"); shift 2 ;;
            --from=*) from=$(parse_layout "${1#--from=}"); shift ;;
            -*) die "不认识的参数：$1" ;;
            *) out="$1"; shift ;;
        esac
    done
    if [ -z "$from" ]; then
        if has_state docker && has_state bare; then
            die "userdata/（Docker）和 automation/（裸机）里都有数据，不知道导哪份。请加 --from docker 或 --from bare"
        elif has_state docker; then
            from=docker
        elif has_state bare; then
            from=bare
        else
            die "没找到任何用户数据（既没有 userdata/ 下的，也没有仓库根 .env / automation/history.json）"
        fi
        say "数据来源：$( [ "$from" = docker ] && echo 'Docker 部署（userdata/）' || echo '裸机部署（仓库根 + automation/）')"
    fi
    if mover_running "$from"; then
        warn "自动搬运正在运行，导出之后它处理的视频不会进这个包，新机器会重投。"
        warn "想零重复：先停掉它（裸机 sudo systemctl disable --now bili-mover，Docker ./docker-start.sh stop）再导出一次。"
    fi

    out="${out:-bilingual-sub-userdata-$(date +%Y%m%d-%H%M).tar.gz}"
    make_stage; local stage="$STAGE"
    mkdir -p "$stage/userdata"
    local f src got=""
    for f in $FILES; do
        src=$(path_of "$from" "$f")
        if [ -s "$src" ]; then
            cp -p "$src" "$stage/userdata/$f"
            got="$got $f"
        fi
    done
    [ -n "$got" ] || die "没有可导出的文件"
    (umask 077; tar czf "$out" -C "$stage" userdata)
    chmod 600 "$out"
    say "已导出到 ${out}，包含：${got# }"
    if [ -s "$stage/userdata/history.json" ]; then
        say "history：$(grep -o '"[^"]*"' "$stage/userdata/history.json" | wc -l | tr -d ' ') 条"
    fi
    cat <<EOT
   到新机器上：
     git clone <本仓库> && cd bilingual-sub-generator
     scripts/migrate.sh import ${out}        # 自动判断新机器是裸机还是 Docker，也可加 --to bare / --to docker
   注意：包里有登录凭据，传完就删。新机器跑通、旧机器停掉之前，不要两边同时开自动搬运。
EOT
}

cmd_import() {
    local archive="" to="" force=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --to) to=$(parse_layout "${2:-}"); shift 2 ;;
            --to=*) to=$(parse_layout "${1#--to=}"); shift ;;
            --force) force=1; shift ;;
            -*) die "不认识的参数：$1" ;;
            *) archive="$1"; shift ;;
        esac
    done
    [ -n "$archive" ] && [ -f "$archive" ] || die "用法: scripts/migrate.sh import <export 打出来的 .tar.gz> [--to bare|docker] [--force]"

    if [ -z "$to" ]; then
        # 已经有 userdata 数据 → Docker；有仓库根 venv（裸机安装的必经步骤）→ 裸机；都没有 → Docker
        if has_state docker; then
            to=docker; say "目标：Docker 部署（userdata/ 里已有数据）"
        elif [ -x venv/bin/python3 ]; then
            to=bare; say "目标：裸机部署（检测到仓库根的 venv/）。不对的话加 --to docker"
        else
            to=docker; say "目标：Docker 部署（没有 venv/，按 Docker 处理）。要装成裸机加 --to bare"
        fi
    fi

    if has_state "$to" && [ -z "$force" ]; then
        die "这台机器上已经有用户数据了，不覆盖。确定要覆盖就加 --force（原文件会备份成 .bak-<时间>）"
    fi
    if mover_running "$to"; then
        warn "这台机器的自动搬运正在运行。导入期间最好先停掉，否则它可能同时在投稿。"
    fi

    make_stage; local stage="$STAGE"
    tar xzf "$archive" -C "$stage"
    [ -d "$stage/userdata" ] || die "包里没有 userdata/ 目录，不是 export 打出来的包"

    local ts f src dst got=""
    ts=$(date +%Y%m%d-%H%M%S)
    for f in $FILES; do
        src="$stage/userdata/$f"
        [ -s "$src" ] || continue
        dst=$(path_of "$to" "$f")
        mkdir -p "$(dirname "$dst")"
        if [ -s "$dst" ] && ! cmp -s "$src" "$dst"; then
            cp -p "$dst" "$dst.bak-$ts"
        fi
        cp "$src" "$dst"
        got="$got $f"
    done
    [ -n "$got" ] || die "包是空的"

    for f in $FILES; do
        dst=$(path_of "$to" "$f")
        [ -f "$dst" ] || continue
        case " $SECRET_FILES " in
            *" $f "*) chmod 600 "$dst" ;;
            *) chmod 644 "$dst" ;;
        esac
    done

    local envf; envf=$(path_of "$to" .env)
    if [ "$to" = docker ]; then
        rm -f userdata/.setup-done
        [ -e userdata/cookies.txt ] || : > userdata/cookies.txt
        if rewrite_proxy_host "$envf" '127\.0\.0\.1' host.docker.internal \
            || rewrite_proxy_host "$envf" localhost host.docker.internal; then
            warn "代理地址里的 127.0.0.1 已换成 host.docker.internal（容器里 127.0.0.1 是容器自己）"
        fi
        # 防止新旧两台机器同时投稿：先关掉，用户确认旧机停了再 ./docker-start.sh setup 打开
        if grep -qE '^ENABLE_AUTOMATION=1' "$envf" 2>/dev/null; then
            sed -i.bak -e 's/^ENABLE_AUTOMATION=1/ENABLE_AUTOMATION=0/' "$envf" && rm -f "$envf.bak"
            warn "已把 ENABLE_AUTOMATION 置 0：等旧机器的服务停掉后，运行 ./docker-start.sh setup 到第 4 步再打开"
        fi
    else
        if rewrite_proxy_host "$envf" host.docker.internal 127.0.0.1; then
            warn "代理地址里的 host.docker.internal 已换成 127.0.0.1（裸机直接访问本机代理）"
        fi
    fi

    say "已导入：${got# }"
    if grep -qE '^(HTTP_PROXY|HTTPS_PROXY)=.+' "$envf" 2>/dev/null; then
        warn "代理端口沿用旧机器的：$(grep -E '^HTTP_PROXY=' "$envf" | head -1 | cut -d= -f2-)。这台机器端口不同的话体检会报出来。"
    fi
    if [ "$to" = docker ]; then
        say "接下来运行 ./docker-start.sh —— 它会先体检，通过就直接启动"
    else
        cat <<EOT
$(echo -e "${GREEN}▶ 接下来：${NC}")
     venv/bin/python3 scripts/setup_wizard.py --check     # 体检代理 / key / cookie
     bash start.sh                                         # Web 界面，先手工跑通一个视频
   确认旧机器的自动搬运已经停掉后，再按 docs/RUNBOOK.md §1 装 systemd 服务（模板 automation/bili-mover.service）。
EOT
    fi
}

case "${1:-}" in
    export) shift; cmd_export "$@" ;;
    import) shift; cmd_import "$@" ;;
    *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
