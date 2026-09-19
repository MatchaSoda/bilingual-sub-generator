import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent.parent

# .env 的位置：裸机在仓库根；Docker 部署下 AUTOMATION_STATE_DIR 指向挂载出来的 userdata/，
# Web 界面「系统设置」写 key 也写到这里，否则写进容器自己的文件系统，重建就丢（docs/DOCKER.md §2）。
_STATE_DIR = os.getenv("AUTOMATION_STATE_DIR")
ENV_FILE = Path(_STATE_DIR) / ".env" if _STATE_DIR else BASE_DIR / ".env"
load_dotenv(ENV_FILE)

BACKEND_SOURCE_DIRECTORY = BASE_DIR / "backend"
FRONTEND_SOURCE_DIRECTORY = BASE_DIR / "frontend"
FRONTEND_DIST = FRONTEND_SOURCE_DIRECTORY / "out"

DATA_STORAGE_DIRECTORY = BASE_DIR / "data"
DOWNLOADS_DIR = DATA_STORAGE_DIRECTORY / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python3"
if not VENV_PYTHON.exists():
    VENV_PYTHON = BASE_DIR.parent / "venv" / "bin" / "python3"

# 代理完全由环境变量决定（.env 或进程环境）。留空 / 不设 = 直连。
# 不再内置 127.0.0.1:10808 这种默认值：它只对某一台机器成立，在容器里 127.0.0.1 是容器
# 自己，会静默连不上。Docker 部署下由 scripts/setup_wizard.py 探测后写进 userdata/.env。
HTTP_PROXY = os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or None
HTTPS_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or HTTP_PROXY

# YouTube cookies（Netscape 格式）。默认在仓库根；Docker 部署用 YT_COOKIES_FILE 指到挂载目录。
# 空文件视为不存在：向导 / 启动脚本会先 touch 一个占位，yt-dlp 拿到空文件会报格式错误。
_COOKIES_FILE = Path(os.getenv("YT_COOKIES_FILE") or (BASE_DIR / "cookies.txt"))
YT_DLP_COOKIES = str(_COOKIES_FILE) if _COOKIES_FILE.is_file() and _COOKIES_FILE.stat().st_size > 0 else None

# Gemini 可选地单独走一条 SOCKS + 本地 DNS 解析的路径，绕开代理服务端的域名分流
# （见 docs/RUNBOOK.md §5.5）。这条绕行只对「代理服务端按域名分流」的部署有意义，
# 所以必须显式设 GEMINI_PROXY 才启用；不设 = 只走进程原有代理，不做任何花活。
GEMINI_PROXY = os.getenv("GEMINI_PROXY") or None
GEMINI_FORCE_IPV4 = os.getenv("GEMINI_FORCE_IPV4", "1") == "1"

GOOGLE_API_KEYS = os.getenv("GOOGLE_API_KEYS", "")
MODEL_NAME = "gemini-3.1-flash-lite"

DEFAULT_STYLE = {
    "font_size_main": 52,
    "main_bottom": 12.0,
    "font_size_sub": 32,
    "sub_bottom": 5.0,
}
