#!/usr/bin/env bash
# 容器入口。三种角色共用一个镜像：
#   web    FastAPI + 前端静态文件，端口 8501
#   mover  自动搬运常驻循环（automation/mover.py）
#   setup  首次设置向导（scripts/setup_wizard.py）
#   其他   原样执行（比如 bash 进容器排查）
#
# 三种角色都可能触发 yt-dlp 下载，而 PO Token 插件要拉起非 headless 的 Chrome，
# 所以统一在这里起一个 Xvfb 虚拟显示（DISPLAY=:99 在 Dockerfile 里设好了）。
set -euo pipefail

cd /app

# ---------- root 阶段：做只有 root 能做的事，然后按 PUID/PGID 降权 ----------
# PUID/PGID 由 docker-start.sh 填成宿主机用户，让 bind mount 出来的文件属主是用户而不是 root（Linux 上
# 否则改 config.json 都要 sudo）。不设就保持 root 运行。
if [ "$(id -u)" = "0" ]; then
    mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
    # 让 nodriver 找得到 Debian 的 chromium（它的搜索列表里有 chromium，这里再兜底一层）
    if ! command -v google-chrome >/dev/null 2>&1 && command -v chromium >/dev/null 2>&1; then
        ln -sf "$(command -v chromium)" /usr/local/bin/google-chrome
    fi
    # 向导 / 启动脚本会先 touch 一个空 cookies.txt 占位；settings.py 和 mover.py 把空文件当不存在
    if [ -n "${YT_COOKIES_FILE:-}" ]; then
        mkdir -p "$(dirname "$YT_COOKIES_FILE")"
        [ -e "$YT_COOKIES_FILE" ] || : > "$YT_COOKIES_FILE"
    fi
    # 只接受纯数字且非 0 的 PUID；其他情况（没设、设成空、设成用户名之类）都按 root 跑
    case "${PUID:-}" in ''|0|*[!0-9]*) PUID="" ;; esac
    if [ -n "${PUID}" ]; then
        PGID="${PGID:-$PUID}"
        case "${PGID}" in ''|*[!0-9]*) PGID="$PUID" ;; esac
        getent group "$PGID" >/dev/null 2>&1 || groupadd -g "$PGID" app
        # -K 放宽 uid 范围：macOS 用户是 501，默认 UID_MIN=1000 会每次启动打一行警告
        getent passwd "$PUID" >/dev/null 2>&1 || useradd -u "$PUID" -g "$PGID" -M -d /tmp -s /bin/bash -K UID_MIN=1 -K UID_MAX=65534 app
        # 命名卷 /models 初始属主是 root；bind mount 的两个目录跟宿主机走。只在顶层属主不对时才 chown -R
        for d in /models /app/userdata /app/data; do
            [ -d "$d" ] || continue
            if [ "$(stat -c %u "$d")" != "$PUID" ]; then chown -R "$PUID:$PGID" "$d" 2>/dev/null || true; fi
        done
        export HOME=/tmp
        exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
    fi
fi

# ---------- 普通阶段（root 或已降权到 PUID） ----------
# -ac 关掉 X 的访问控制：容器里只有我们自己，而降权后的进程要连得上它
if [ -n "${DISPLAY:-}" ] && ! pgrep -x Xvfb >/dev/null 2>&1; then
    Xvfb "${DISPLAY}" -screen 0 1280x800x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &
    # 给 X server 一点启动时间；起不来也不阻塞（只影响 PO Token → 画质）
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [ -e "/tmp/.X11-unix/X${DISPLAY#:}" ]; then break; fi
        sleep 0.3
    done
fi

case "${1:-web}" in
    web)
        # 没跑过向导就先提醒，但不阻塞：Web 界面本身能起来，只是提交任务会失败
        if [ -n "${AUTOMATION_STATE_DIR:-}" ] && [ ! -f "${AUTOMATION_STATE_DIR}/.setup-done" ]; then
            echo "⚠️  还没跑过首次设置向导，请先在宿主机执行: ./docker-start.sh setup" >&2
        fi
        cd /app/backend
        exec /app/venv/bin/python3 entry_server.py
        ;;
    mover)
        if [ -n "${AUTOMATION_STATE_DIR:-}" ] && [ ! -f "${AUTOMATION_STATE_DIR}/config.json" ]; then
            echo "❌ 缺少 ${AUTOMATION_STATE_DIR}/config.json，自动搬运无法启动。请先执行: ./docker-start.sh setup" >&2
            # 睁眼等着而不是崩溃重启刷屏；用户跑完向导后 docker compose restart mover 即可
            exec sleep infinity
        fi
        cd /app/automation
        exec /app/venv/bin/python3 mover.py
        ;;
    setup)
        shift
        exec /app/venv/bin/python3 /app/scripts/setup_wizard.py "$@"
        ;;
    --*)
        # `docker compose run setup --check` 会把 --check 当成整个 command 传进来（compose 的 run 是替换而不是追加）
        exec /app/venv/bin/python3 /app/scripts/setup_wizard.py "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
