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

if [ -n "${DISPLAY:-}" ] && ! pgrep -x Xvfb >/dev/null 2>&1; then
    Xvfb "${DISPLAY}" -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    # 给 X server 一点启动时间；起不来也不阻塞（只影响 PO Token → 画质）
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if [ -e "/tmp/.X11-unix/X${DISPLAY#:}" ]; then break; fi
        sleep 0.3
    done
fi

# 让 nodriver 找得到 Debian 的 chromium（它的搜索列表里有 chromium，这里再兜底一层）
if ! command -v google-chrome >/dev/null 2>&1 && command -v chromium >/dev/null 2>&1; then
    ln -sf "$(command -v chromium)" /usr/local/bin/google-chrome
fi

# 向导 / 启动脚本会先 touch 一个空 cookies.txt 占位；settings.py 和 mover.py 把空文件当不存在
if [ -n "${YT_COOKIES_FILE:-}" ]; then
    mkdir -p "$(dirname "$YT_COOKIES_FILE")"
    [ -e "$YT_COOKIES_FILE" ] || : > "$YT_COOKIES_FILE"
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
    *)
        exec "$@"
        ;;
esac
