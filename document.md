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

- 用户输入视频 URL。
- 配置 ASR 模型大小、翻译目标语言和 AI 修正选项。
- 快速启动生成流程。

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

- 通过轮询后端接口，展示任务执行的原始实时日志。
- 可视化展示当前处理步骤（下载、转录、翻译等）。

### 3.4 媒体库 (Library Panel)

- 展示已生成的视频列表。
- 支持在线播放生成的双语字幕视频。
- 提供删除功能，清理存储空间。

### 3.5 系统设置 (Settings Panel)

- 管理 Google Gemini API Key。
- 支持多 Key 轮询配置。

---

## 4. 自动化搬运模块 (Automation)

`automation/` 目录下提供了一个独立运行的自动化搬运服务，能够自动发现视频、处理并投稿至 Bilibili。

### 4.1 核心组件

- **mover.py**: 基于 `yt-dlp` 和 `biliup` 的主程序。它会定期扫描指定的 YouTube 频道，若发现符合条件的视频（如包含特定关键字），则自动调用本系统的 CLI 工具进行下载、翻译和压制。
- **config.json**: 核心配置文件（参考 `config.json.example`），用于管理监听频道、B 站投稿分区 (TID) 以及扫描间隔。
- **bili-mover.service**: 为 Linux 系统设计的 systemd 服务文件，支持将搬运程序作为后台常驻进程运行。

### 4.2 运行流程

1. **登录 B 站**: 运行相应工具生成 `cookies.json`。
2. **配置频道**: 复制 `config.json.example` 为 `config.json`，并填入你感兴趣的 YouTube 频道 URL 和过滤关键字。
3. **启动服务**:
   - 手动运行: `python mover.py`
   - 服务运行: 将 `bili-mover.service` 文件复制到 `/etc/systemd/system/` 并启动。

---

## 5. 数据流图

1. **前端** 发送 `SubtitleRequest` 到 **后端 API**。
2. **后端 `job_manager`** 启动 `entry_cli.py` 子进程。
3. `media_downloader` 下载音视频 -> `transcription_engine` 生成 JSON -> `segment_optimizer` 优化分段 -> `subtitle_translator` 请求 Gemini 翻译 -> `subtitle_generator` 生成 ASS -> `video_processor` 压制 MP4。
4. **前端 `TelemetryPanel`** 轮询获取实时日志与进度。
5. 完成后，视频显示在 **前端 `LibraryPanel`**。

---

## 6. 开发与部署

- **运行环境**: 建议使用 Python 3.10+ 和 Node.js 18+。
- **启动脚本**: `start.sh` 可一键启动前后端服务。
- **依赖管理**:
  - Python: `pip install -r requirements.txt`
  - Node.js: `npm install` (在 frontend 目录下)
