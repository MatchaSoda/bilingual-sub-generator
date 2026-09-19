# 🍵 双语字幕生成器

> 这个项目是 Vibe Coding 的产物

一个自动化的日语/中文双语字幕生成与视频压制系统。它能自动下载 YouTube 视频，通过 AI 语音识别和翻译，生成双语字幕视频。

## ✨ 核心特性

- 🎙️ **精准转录**: 基于 `faster-whisper` 的高效语音识别。
- 🤖 **智能翻译**: 使用 Google Gemini AI，具备上下文感知的翻译与原文纠错能力。
- 🏮 **假名标注**: 自动为日语汉字添加振假名（Furigana），助力语言学习。
- 🎨 **视觉实验室**: 前端实时预览并自定义字幕样式（字体、颜色、边框、阴影、位置）。
- 📺 **全自动压制**: 集成 FFmpeg，一键生成硬压制双语视频。
- 🛰️ **自动化搬运**: 定期扫描 YouTube 频道并自动同步处理结果至 Bilibili。

## 🚀 快速开始

### 方式 A：Docker 一键（推荐给新机器）

```bash
./docker-start.sh     # 首次会构建镜像并进入设置向导，按提示填代理 / key / cookie
```

向导会逐步验证每项配置。换机器：旧机 `./docker-start.sh export`，新机 `./docker-start.sh import <包>` 再 `./docker-start.sh`。详见 [docs/DOCKER.md](./docs/DOCKER.md)。

### 方式 B：裸机安装（直接跑在自己电脑 / 服务器上）

#### 1. 系统依赖

| 需要 | 干什么用 | 缺了会怎样 |
|---|---|---|
| Python 3.10+、Node.js 18+ | 后端 / 前端构建 | 起不来 |
| FFmpeg | 压制 | 起不来 |
| Chrome 或 Chromium | yt-dlp 取 PO Token（`yt-dlp-getpot-wpc` 会拉起一个真实浏览器） | 能跑，但 YouTube 只给 360p |
| Noto Sans CJK 字体（Debian/Ubuntu：`fonts-noto-cjk`） | 字幕样式写死了这个字体 | ffmpeg 静默换字体，出现方块 |
| 无桌面的 Linux 服务器：Xvfb | 上面那个浏览器不是 headless 的，需要一个显示 | 拿不到 PO Token，同上 360p |

JS 运行时（yt-dlp 解 YouTube 挑战用的 deno）随 `pip install` 一起装，不用单独装。

#### 2. 初始化

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt   # 一定要用仓库根的 venv，脚本都按这个路径找解释器
cd frontend && npm install && cd ..
venv/bin/python3 scripts/setup_wizard.py                            # 和 Docker 同一个向导：代理 / Gemini key / cookie / 频道，逐项联网验证
```

向导把配置写到仓库根的 `.env`、`cookies.txt` 和 `automation/config.json`。以后想体检：`venv/bin/python3 scripts/setup_wizard.py --check`。

#### 3. 运行

```bash
bash start.sh              # Web 界面 http://localhost:8501（首次会构建前端）
```

自动搬运（常驻扫描频道 → 投稿 B 站）以 systemd 服务方式运行，模板在 `automation/bili-mover.service`，操作见 [docs/RUNBOOK.md](./docs/RUNBOOK.md) §1。
裸机上所有文件都是你自己的用户创建的，没有 Docker 那种属主问题。

## 📖 文档与 Wiki

- **[技术文档 (Wiki)](./document.md)**: 系统架构、详细配置参数、技术路径以及自动化模块的深入说明。
- **[运维手册 (Runbook)](./docs/RUNBOOK.md)**: 服务操作、凭据更新、故障处置与验证脚本。
- **[当前进展 (Progress)](./docs/PROGRESS.md)**: 最近改动、已知问题与技术债。
- **[CLAUDE.md](./CLAUDE.md)**: 给 AI 协作者的项目约定。
