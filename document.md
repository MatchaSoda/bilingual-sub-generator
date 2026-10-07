# 双语字幕生成器 Wiki

> 本文档深入探讨本项目的内部架构、技术实现路径以及核心配置说明。
> 快速入门请参阅 [README.md](./README.md)。

---

## 1. 系统架构与技术路径

本系统采用现代化的解耦架构，结合多项 AI 能力：

- **前端 (Frontend)**: 基于 **Next.js 15** 和 **React 19**，使用 **Material UI (MUI)** 构建响应式仪表盘。
- **后端 (Backend)**: 基于 **FastAPI**，负责任务调度、媒体处理和 AI 接口调用。
- **核心能力**:
  - **下载**: 使用 `yt-dlp` 处理网络视频。
  - **语音识别 (ASR)**: 使用 `faster-whisper` (CTranslate2) 进行高效转录。
  - **翻译 (Translation)**: 使用 **Google Gemini AI** 进行上下文感知的高质量翻译。
  - **字幕渲染**: 生成复杂的 **ASS** 字幕，支持日语 **Furigana (振假名)**。
  - **视频合成**: 使用 `FFmpeg` 进行字幕硬压制。

---

## 2. 后端功能实现 (Backend)

后端代码位于 `backend/` 目录下，具有明确的模块划分：

### 2.1 任务调度系统 (`services/job_manager.py`)

- **异步处理**: 使用 FastAPI 的 `BackgroundTasks` 在后台启动处理进程。
- **进程隔离**: 每个任务通过 `subprocess` 调用 `entry_cli.py` 运行，确保任务之间互不干扰，并能实时捕获标准输出日志。
- **状态追踪**: 提供任务状态（Pending, Processing, Completed, Failed）和实时日志查询接口。

### 2.2 核心处理流水线 (`engines/`)

- **媒体下载 (`media_downloader.py`)**: 封装 `yt-dlp`，支持自动提取最佳音视频流及相关元数据。
- **语音识别 (`transcription_engine.py`)**: 调用 Whisper 模型，支持从 `tiny` 到 `large-v3` 的多种规格，具备自动语言检测功能。
- **分段优化 (`segment_optimizer.py`)**: 针对 Whisper 的原始输出进行断句优化和切分，确保字幕长度符合视觉习惯。
- **字幕翻译 (`subtitle_translator.py`)**:
  - 批量处理字幕段落以提高效率。
  - 支持 `fix_source` 模式，利用 AI 修正 ASR 识别错误，并输出高质量的双语结果。
- **字幕生成 (`subtitle_generator.py`)**:
  - 生成 ASS 格式字幕，支持三层渲染（主字幕、副字幕、日语振假名）。
  - 支持自定义字体大小、透明度、边框、阴影和垂直位置。
- **视频处理 (`video_processor.py`)**:
  - 使用 `ffprobe` 获取视频分辨率以精确对齐字幕。
  - 使用 `ffmpeg` 的 `subtitles` 滤镜进行硬压制。

### 2.3 API 与配置

- **API 路由 (`api/`)**: `routes.py` 和 `schemas.py` 定义了前后端交互的 RESTful 接口及 Pydantic 数据模型。
- **系统配置 (`config/`)**: `settings.py` 和 `keys.py` 负责加载和验证环境变量、API Key 及系统级设置。

### 2.4 辅助工具 (`utils/`)

- **Furigana 注音 (`furigana_generator.py`)**: 利用 `MeCab` 为日语文本自动添加汉字注音。
- **缩略图辅助 (`thumbnail_helper.py`)**: 处理视频封面的下载与格式转换。

---

## 3. 前端功能实现 (Frontend)

前端代码位于 `frontend/` 目录下，采用单页应用 (SPA) 设计，包含以下核心面板 (`app/components/`)：

### 3.1 制作任务 (Task Panel)

- 用户输入视频 URL，两种模式（选择记在 localStorage）：
  - **仅生成字幕视频**：用「系统设置」的模型和「视觉实验室」的样式，后端 `job_manager` 直接跑 `entry_cli.py`，成品进媒体库。
  - **生成并投稿 B 站**：只收 YouTube 单个视频链接。任务交给自动搬运的 mover 排队执行（见 §4.3），处理参数、样式、
    投稿模板用「自动搬运 › 处理与投稿」里的预设；分区、标签、B 站标题可以按这一次覆盖。前一个没完也能继续提交。
- 视频已经投过稿（`uploads.jsonl` 有记录）或在自动搬运的 history 里但不知道是不是被过滤掉的，提交时会先确认一次。

### 3.2 视觉实验室 (Design Panel)

- **实时样式调整**: 提供细粒度滑块，控制字体大小、颜色、透明度、边框厚度、阴影深度和垂直位置。
- **主/副字幕分离控制**: 分别设置主标题（如日文）、副标题（如中文）和注音（Furigana）的独立样式。
- **WebAssembly 实时预览引擎 (核心技术)**:
  - 采用 **`libass-wasm` (JASSUB)** 作为底层渲染引擎。这是一个将 C/C++ 编写的 `libass` 库编译为 WebAssembly 的项目，专门用于在浏览器中渲染 ASS (Advanced SubStation Alpha) 格式字幕。
  - **工作原理**: 当用户调整前端的样式滑块时，React 的 `useMemo` 会动态在内存中实时构建一段完整的 ASS 脚本（包含样式定义 `[V4+ Styles]` 和对话事件 `[Events]`）。
  - **渲染过程**: 前端创建一个隐藏透明的 HTML `<canvas>` 覆盖在预览容器上。随后，实例化 `SubtitlesOctopus`，加载本地字体文件（如 `NotoSansCJK`），并挂载生成的 ASS 内容。
  - **优势**: 每次参数变动仅需调用 `subInstance.setTrack()` 并触发重绘，实现了**零延迟、无服务器交互**的所见即所得效果。更重要的是，它保证了浏览器端预览的画面与最终 `FFmpeg` 压制生成的视频字幕在**像素级别上完全一致**。
- **配置持久化**: 所有样式参数自动保存至浏览器的 `localStorage`。

### 3.3 实时遥测 (Telemetry Panel)

- 通过轮询 `/api/status/{id}` 展示当前任务的实时日志。Web 任务和投稿任务走同一个接口（投稿任务 id 以 `pub-` 开头，
  后端从共享的 `jobs/` 目录读）。刷新页面后会接着显示上一个任务（投稿任务在 userdata 里，服务重启也还在）。
- 分阶段进度：下载 → 转写 → 翻译 → 压制（→ 投稿）。阶段由后端从 `entry_cli` 的输出行推断（`backend/utils/pipeline_stages.py`，
  Web 任务和 mover 共用一张表），失败时标红停在出错的那一步。
- 投稿任务额外显示：排在队列第几、mover 正在忙什么、投稿结果和 BV 号链接；排队时可以取消，失败可以重试。

### 3.4 媒体库 (Library Panel)

- 展示已生成的视频列表，包括 Web 任务的成品（`data/downloads`）和自动搬运的成品（`userdata/data`，裸机 `automation/data`），
  封面上标「手动制作」或「自动搬运」。后端逻辑在 `backend/utils/library.py`，自动搬运的文件经 `/api/outputs` 提供。
- 按来源筛选、按标题搜索；按时间、大小、名称排序。来源和排序记在浏览器 localStorage。
- 支持在线播放生成的双语字幕视频。
- 提供删除功能，清理存储空间。「Clear Hub」只删当前筛选后看得到的视频。
  自动搬运的成品还会被 mover 按 `cleanup.keep_days` 定期删除（RUNBOOK §4）。

### 3.5 系统设置 (Settings Panel)

- 管理 Google Gemini API Key（多 Key 逗号分隔轮询）。写进 `.env`（Docker 是 `userdata/.env`），Web 任务和自动搬运共用：
  `config/keys.py` 先读文件再读环境变量，所以 mover 容器不用重建，下一个视频就用新 Key。
- 下面的模型和开关只管「仅生成」的任务；投稿用自动搬运页的预设（那边可以一键导入这里的设置）。

### 3.6 自动搬运 (Automation Panel，`app/components/automation/`)

和 mover 进程通过 userdata 下的共享文件协作（§4.3），Web 自己不投稿。六个标签页：

| 标签 | 内容 |
|---|---|
| 概览 | mover 在不在线、在干什么（扫描 / 处理哪个视频的哪一步 / 休眠到几点）、上一轮统计、24 小时投稿 / 失败 / 跳过原因；「立即扫描」「暂停 / 恢复自动扫描」；投稿队列（取消、重试、看日志）；B 站账号（登录状态、到期日、扫码登录）；最近动态 |
| 频道 | 频道列表增删改排序：地址、关键词、排除词、分区、标签 |
| 扫描规则 | 扫描间隔、每轮看多少个视频、每轮上限、拉简介间隔、补档范围（起点水位）、媒体保留天数 |
| 处理与投稿 | 处理预设（模型、断句、振假名、纠错、字幕样式）、上传线路和重试、B 站标题 / 简介模板（带预览） |
| 投稿记录 | `uploads.jsonl`：时间、B 站标题、BV 号、原视频、来源（自动 / Web / 补投脚本） |
| 日志 | `runtime/mover.log` 的最后 800 行，自动刷新 |

配置页改的是一份草稿，点保存才写 `config.json`（带版本号：向导或手工改过文件就拒绝覆盖，提示重新加载）；有没保存的修改时
切走页面会确认。视觉实验室的「设为投稿样式」直接把当前样式写进 `processing.style`。

---

## 4. 自动化搬运模块 (Automation)

`automation/` 目录下提供了一个独立运行的自动化搬运服务，能够自动发现视频、处理并投稿至 Bilibili。

### 4.1 核心组件

- **mover.py**: 基于 `yt-dlp` 和 `biliup` 的主程序。它会定期扫描指定的 YouTube 频道，若发现符合条件的视频（如包含特定关键字），则自动调用本系统的 CLI 工具进行下载、翻译和压制。
- **config.json**: 核心配置文件（参考 `config.json.example`），用于管理监听频道、B 站投稿分区 (TID) 以及扫描间隔。
- **bili-mover.service**: 为 Linux 系统设计的 systemd 服务文件，支持将搬运程序作为后台常驻进程运行。

### 4.2 运行流程

1. **登录 B 站**: Web「自动搬运」页扫码登录（或终端里 `biliup login`），生成 `cookies.json`。
2. **配置频道**: 在「自动搬运 › 频道」里添加（或复制 `config.json.example` 为 `config.json` 手改）。
3. **启动服务**:
   - Docker: `userdata/.env` 里 `ENABLE_AUTOMATION=1`，然后 `./docker-start.sh`（起 `mover` 容器）。
   - 裸机: `python mover.py`，或者把 `bili-mover.service` 复制到 `/etc/systemd/system/` 并启动。

### 4.3 Web 和 mover 怎么协作

两个进程（Docker 里是 `web`、`mover` 两个容器）不互相调用，只读写 STATE_DIR（Docker `userdata/`，裸机 `automation/`）下的文件，
布局和读写函数都在 `backend/utils/automation_store.py`（只用标准库，mover 直接 import）：

```
config.json          Web 改（带版本号、原子写、上一版留在 config.json.bak-last），mover 每轮重读
uploads.jsonl        mover 每次投稿成功追加一行（BV 号、YouTube ID、成品文件名、来源）
jobs/<id>.json/.log  Web 提交的投稿任务；mover 按提交顺序认领、执行、写结果
runtime/status.json  mover 每 5 秒写一次心跳和当前状态，Web 据此显示在线 / 离线
runtime/events.jsonl 跳过、命中、失败、投稿成功、一轮结束、清理，概览页的动态和统计
runtime/mover.log    mover 输出的副本（带时间戳），日志页
runtime/wake         「立即扫描」：mover 休眠时每 3 秒看一眼，有就提前开始下一轮
```

- **只有 mover 投稿。** 「生成并投稿」的任务和频道扫描在同一个进程里串行执行：每轮开头、两个视频之间、休眠期间都会先跑
  排队的 Web 任务，所以用户最多等一个视频；也不会两边同时压视频、同时投同一个视频（扫描时跳过有 Web 任务的视频）。
- 写 `jobs/`、`uploads.jsonl`、`config.json` 都在 `runtime/*.lock` 的 `flock` 里做；两个容器共用一个内核，flock 跨容器有效。
- 投稿任务成功后由 mover 写 history（同一个进程，内存集合就是权威，RUNBOOK §3 的语义不变）；每轮开头 mover 还会把磁盘上的
  history 并进内存，吸收 backfill.py 这类外部写入。
- mover 重启时还在跑的任务标成失败、不自动重跑：中断可能发生在投稿成功之后、记账之前（RUNBOOK §9）。
- 「暂停自动扫描」是 `config.json` 的 `paused`：不扫频道，但 Web 投稿照常处理。部署层面的开关仍是 `.env` 的 `ENABLE_AUTOMATION`。

---

## 5. 数据流图

仅生成：

1. **前端** 发送 `SubtitleRequest` 到 **后端 API**。
2. **后端 `job_manager`** 启动 `entry_cli.py` 子进程。
3. `media_downloader` 下载音视频 -> `transcription_engine` 生成 JSON -> `segment_optimizer` 优化分段 -> `subtitle_translator` 请求 Gemini 翻译 -> `subtitle_generator` 生成 ASS -> `video_processor` 压制 MP4。
4. **前端 `TelemetryPanel`** 轮询获取实时日志与进度。
5. 完成后，视频显示在 **前端 `LibraryPanel`**。

生成并投稿：

1. **前端** `POST /api/automation/jobs` → 后端写 `jobs/pub-….json`（状态 queued）。
2. **mover** 认领任务 → 拿标题 → `publish_video`：同样起 `entry_cli.py`，参数来自 `config.json` 的 `processing`，成品写到 userdata/data
   → `biliup upload` → 写 `uploads.jsonl`、history、任务结果（BV 号）。
3. **前端 `TelemetryPanel`** 同样轮询 `/api/status/pub-…`，日志来自 `jobs/pub-….log`。

---

## 6. 开发与部署

- **运行环境**: 建议使用 Python 3.10+ 和 Node.js 18+。
- **启动脚本**: `start.sh` 可一键启动前后端服务。
- **依赖管理**:
  - Python: `pip install -r requirements.txt`
  - Node.js: `npm install` (在 frontend 目录下)
