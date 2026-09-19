# 双语字幕生成器：一个镜像同时承担 Web 服务、自动搬运、首次设置向导（见 docker-compose.yml）。
# 构建期做两件事：node 阶段把 Next.js 前端静态导出；python 阶段装 venv + 系统依赖。
# venv 固定在 /app/venv —— mover.py / settings.py 用相对仓库根的 venv/bin/... 找解释器和 yt-dlp、biliup。

# ---------- 阶段 1：前端静态导出 ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /frontend
# playwright-chromium 在 devDependencies 里，npm ci 会顺手下载 300MB 浏览器；这里只需要 build，跳过。
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：运行镜像 ----------
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Whisper 模型缓存，compose 里挂成命名卷，镜像重建不用重下 1.6GB
    HF_HOME=/models \
    # yt-dlp 的 PO Token 插件要拉起「非 headless」Chrome，entrypoint 起一个 Xvfb 给它
    DISPLAY=:99 \
    IN_DOCKER=1 \
    TZ=Asia/Tokyo

# ffmpeg      压制
# fonts-noto-cjk  字幕样式写死了 Noto Sans CJK JP/SC，缺了会静默换字体（豆腐块）
# chromium + xvfb  yt-dlp-getpot-wpc 取 PO Token（RUNBOOK §5.3）
# tzdata      日志时间
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-cjk fontconfig \
        chromium xvfb \
        ca-certificates curl tzdata procps \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# venv/bin 进 PATH：yt-dlp 子进程按名字找 deno（JS 运行时，pip 装的），排查时也能直接敲 yt-dlp / biliup。
# 放在 apt 层之后：改 ENV 会让后面的层缓存全失效，别让它连累 5 分钟的 apt 层。
ENV PATH=/app/venv/bin:$PATH
COPY requirements.txt ./
RUN python -m venv /app/venv \
    && /app/venv/bin/pip install --upgrade pip \
    && /app/venv/bin/pip install -r requirements.txt

COPY backend/ ./backend/
COPY automation/mover.py automation/backfill.py automation/config.json.example ./automation/
COPY scripts/ ./scripts/
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --from=frontend /frontend/out ./frontend/out
RUN chmod +x /app/docker/entrypoint.sh scripts/setup_wizard.py \
    && mkdir -p /app/data/downloads /app/userdata /models

EXPOSE 8501
ENTRYPOINT ["/app/docker/entrypoint.sh"]
# 默认起 Web 服务；mover / setup 在 compose 里覆盖 command
CMD ["web"]
