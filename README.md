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

### 1. 环境准备

确保你的系统已安装 `Python 3.10+`, `Node.js 18+` 和 `FFmpeg`。

### 2. 初始化项目

```bash
# 安装 Python 依赖 (建议在 venv 中)
pip install -r requirements.txt

# 安装前端依赖 (在 frontend 目录下)
cd frontend && npm install && cd ..
```

### 3. 运行系统

直接运行根目录下的启动脚本：

```bash
bash start.sh
```

访问 `http://localhost:8501` 即可进入 Web 管理界面。

## 📖 文档与 Wiki

- **[技术文档 (Wiki)](./document.md)**: 关于系统架构、详细配置参数、技术路径以及自动化模块的深入说明。
