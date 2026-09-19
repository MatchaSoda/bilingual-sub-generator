# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

日语视频 → 中日双语硬字幕视频的全自动流水线。两种用法共用同一套后端：

- **交互式**：Web UI（Next.js + FastAPI），手工提交单个 URL，可实时调字幕样式。
- **无人值守**：`automation/mover.py` 作为 systemd 常驻服务，定期扫描 YouTube 频道 → 生成双语视频 → 自动投稿 B 站。

**这是一个长期在线运行的生产服务**，不是纯代码库。改动 `automation/` 或 `backend/engines/media_downloader.py` 会直接影响正在跑的 `bili-mover.service`。动手前先读 `docs/RUNBOOK.md`。

## 文档分工

| 文件 | 内容 | 何时读 |
|---|---|---|
| `CLAUDE.md`（本文件） | 命令、架构、AI 维护约定 | 每次开工 |
| `docs/RUNBOOK.md` | 运维手册：服务操作、凭据、故障处置、**踩过的坑** | 碰 automation / 下载 / 投稿时 |
| `docs/PROGRESS.md` | 当前状态、进行中的工作、已知问题 | 每次开工，改完后更新 |
| `docs/DOCKER.md` | Docker 部署：目录约定、向导、限制 | 碰 Dockerfile / compose / setup_wizard 时 |
| `document.md` | 架构与前端技术细节（libass-wasm 预览等） | 需要深入某模块时 |
| `README.md` | 面向用户的安装与快速开始 | 很少 |
| `TODO.md` | 产品功能待办（非工程问题） | 规划功能时 |

## 常用命令

两套部署方式：**裸机**（WSL2 生产机，venv 在仓库根）和 **Docker**（macOS 开发机，venv 在容器 `/app/venv`）。
先看 `.git` 旁边有没有 `venv/`：没有就是 Docker 机，下面的命令都要套进容器跑。

所有 Python 命令都用仓库内的 venv，**不要用系统 python3**（依赖只装在 venv 里）：

```bash
# 测试（51 个用例，unittest，约 1 秒；config/keys.py 导入期要求 GOOGLE_API_KEYS 非空）
bash run_tests.sh
# Docker 机上的等价写法（测试需要一个占位 key）
docker compose run --rm -T -e GOOGLE_API_KEYS=x setup bash -c 'cd /app/backend && /app/venv/bin/python3 -m unittest discover -s tests -p "test_*.py"'
# 跑单个测试文件 / 单个用例
cd backend && ../venv/bin/python3 -m unittest tests.test_segment_optimizer -v
cd backend && ../venv/bin/python3 -m unittest tests.test_segment_optimizer.ClassName.test_method

# 启动 Web 服务（含前端构建），http://localhost:8501
bash start.sh
bash start.sh dev          # 强制重新构建前端

# 单个视频跑完整流水线（不投稿）
cd backend && ../venv/bin/python3 entry_cli.py "<youtube_url>" --segment-mode rule --enable-furigana

# 前端
cd frontend && npm run build && npm run lint
```

Docker 部署：`./docker-start.sh`（首次进向导；改了 `userdata/.env` 后也用它，它会重建容器，`docker compose restart` 不会重读 env）、
`./docker-start.sh check`（体检配置）、`./docker-start.sh model`（确保 Whisper 模型在，启动时自动做）、`./docker-start.sh shell`（进容器）。任何要在容器里跑的一次性命令用
`docker compose run --rm -T setup bash -c '...'`；改了 `backend/` 或 `scripts/` 要 `docker compose build` 后 `up -d` 才生效（代码是 COPY 进镜像的，不是挂载）。

自动化服务的操作命令见 `docs/RUNBOOK.md`（涉及 systemd 和状态文件，有顺序要求）。

## 架构要点

### 流水线是单向的，靠子进程隔离

```
entry_cli.py  ──►  media_downloader (yt-dlp)
                   → transcription_engine (faster-whisper)
                   → segment_optimizer | llm_segmenter   ← 二选一
                   → subtitle_translator (Gemini)
                   → subtitle_generator (ASS)
                   → video_processor (ffmpeg 硬压制)
```

`entry_cli.py` 是**唯一**的流水线入口。三个调用方都通过 `subprocess` 起它，而不是 import：

- `backend/services/job_manager.py` ← Web UI 提交任务
- `automation/mover.py` ← 自动搬运
- `automation/backfill.py` ← 单条补投

**这个设计有个重要后果**：改 `backend/` 下的代码**不需要重启** `bili-mover.service`，因为每个视频都新起一个 `entry_cli.py` 进程。只有改 `automation/mover.py` 本身才需要重启。

### 中间产物有缓存，会跳过重算

`data/downloads/` 下按视频标题存放 `.asr.json`（转写）和 `.translated.json`（翻译）。**只要文件存在就直接复用，不会重跑**。调试翻译逻辑时如果发现改了没效果，先删对应的 `.translated.json`。

### 两种分段模式

`--segment-mode rule`（默认，离线 MeCab + 标点 + 停顿）和 `llm`（Gemini 语义分段）。`llm_segmenter.py` 里的注释解释了每个切点约束存在的原因（形态素边界门控、停顿由词级时间戳推导而非模型回显等）——**那些是算法说明，属于代码，不要往文档里搬**。

### 配置的三个来源

1. `.env` → `GOOGLE_API_KEYS`（逗号分隔，`config/keys.py` 轮询使用）
2. `backend/config/settings.py` → 路径、代理、cookie 位置、默认字幕样式
3. `automation/config.json` → 频道列表、过滤规则、`processing` 段的流水线参数、`backfill` 段的起点水位（RUNBOOK §4）

运行期标记 `automation/state.json`（Docker：`userdata/state.json`）只存首次启动时间，删掉即重置起点。

代理**没有内置默认值**，`.env` 不写就是直连。Docker 部署下所有用户数据集中在 `userdata/`，
代码靠 `AUTOMATION_STATE_DIR` 和 `YT_COOKIES_FILE` 两个环境变量找到它们（见 `docs/DOCKER.md` §2）。

`automation/config.json` **每轮循环重新读取**，改了不用重启服务。

## AI 维护约定

这个项目是被 AI 长期维护的，请遵守：

1. **运维经验写进 `docs/RUNBOOK.md`，不要堆在代码注释里。** 代码注释只留一句「为什么是这个值」+ 指向 runbook 的锚点。判断标准：如果这段知识是「某天线上炸了才知道的」，它属于 runbook；如果是「读这行代码需要知道的」，它属于注释。
2. **改完更新 `docs/PROGRESS.md`。** 特别是留下未完成的事、或发现了新问题时。下一个接手的实例只看这个文件判断现状。
3. **碰 `automation/history.json` 前先读 runbook 的「history.json 语义」。** 它有并发写回语义，直接改文件会被运行中的进程覆盖。
4. **验证靠实测，不靠推理。** 这个项目的失败大多是外部服务（YouTube 风控、B 站 CDN、代理）造成的，同样的配置可能今天能跑明天不行。改完 yt-dlp / 投稿相关的东西，按 runbook 里的验证脚本实际跑几次看成功率，不要只看代码对不对。
5. **不要把测试从 unittest 迁到 pytest**，`run_tests.sh` 依赖 `unittest discover`。
6. **任务做完自己提交**，不要留一堆未提交改动等用户开口。按下面的规范拆分和撰写。

## 提交规范

一个任务完成即提交。**按逻辑变更拆分成多个 commit**，不要把无关改动堆成一个——
本次的过滤修复、下载客户端、投稿重试、文档是四件独立的事，就该是四个 commit。

### Subject

```
<scope>: <小写祈使句，不加句号>
```

- scope 用 `backend` / `automation` / `deps` / `docs` / `docker`
- 长度控制在 50~80 字符
- 描述**做了什么**，不是「修了 bug」

### Body（必写，英文，约 72 字符换行）

这个仓库的 commit body 是主要的知识载体，要按这个顺序写：

1. **症状** —— 用户/日志看到的是什么
2. **机制** —— 为什么会这样，尤其是静默失败的那种
3. **改动** —— 多项时用 `-` 列表
4. **验证** —— 具体证据，不是「测过了」

验证那段是硬要求。参考已有提交的写法：`Verified: tv_simply alone completes
248MB and 272MB downloads (3/3 runs, 2 videos)`、`format 399+251, av1 1920x1080`。
带上次数、数值、样本量。

**如果推翻了之前 commit 的结论，要在 body 里明确写出来。** 例如 `80024c8` 里的
「The previous commit blamed the client list for the missing token. That was
wrong -- ...」。这类记录比结论本身更有价值。

### Trailer

用当前实际在写代码的模型名，不要照抄别人的：

```
Co-Authored-By: <实际模型名> <noreply@anthropic.com>
```

### 不要做的事

- 不要提交 `cookies.txt`、`.env`、`automation/config.json`（都已 gitignore，含凭据）
- 不要在没有跑 `bash run_tests.sh` 的情况下提交
- 未经用户同意不要 push

## 环境约束

### 裸机生产机（WSL2，跑着 `bili-mover.service`）

- 代理在 `127.0.0.1:10808`。**这个端口是 SOCKS5，不是 HTTP**——`http://127.0.0.1:10808` 对部分站点可用、对另一些会连接失败，这已经造成过线上故障，详见 runbook。
- systemd 服务的环境变量里同时有 `HTTP_PROXY`(http://) 和 `ALL_PROXY`(socks5://)，子进程会继承，注意这对 `biliup` 的影响。
- `sudo systemctl` 需要密码，AI 无法直接执行，需要请用户在会话里用 `! sudo systemctl ...` 运行。

### Docker 开发机（macOS，Apple Silicon，Docker Desktop）

- 代理是 Clash Verge 混合端口 `127.0.0.1:7897`，shell 里有 `HTTP_PROXY=http://127.0.0.1:7897`。容器里要写
  `http://host.docker.internal:7897`（已在 `userdata/.env`）。shell 里的代理变量**不会**被 buildx 带进构建容器
  （09-19 实测），也不会进运行容器，不用特意 `env -u`。
- 宿主机 DNS 是 114.114.114.114，会把 `auth.docker.io` 解析到 Dropbox 网段，拉镜像偶发 `i/o timeout`，重试即可（DOCKER.md §4）。
- 容器直连和经代理都能到 YouTube；但没有 cookie 时 mweb 客户端一律 `not a bot`，别拿无 cookie 的结果判断网络。
- 镜像是原生 arm64，biliup 有 aarch64 wheel，不要加 `platform: linux/amd64`。
