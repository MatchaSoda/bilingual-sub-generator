import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent.parent

BACKEND_SOURCE_DIRECTORY = BASE_DIR / "backend"
FRONTEND_SOURCE_DIRECTORY = BASE_DIR / "frontend"
FRONTEND_DIST = FRONTEND_SOURCE_DIRECTORY / "out"

DATA_STORAGE_DIRECTORY = BASE_DIR / "data"
DOWNLOADS_DIR = DATA_STORAGE_DIRECTORY / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python3"
if not VENV_PYTHON.exists():
    VENV_PYTHON = BASE_DIR.parent / "venv" / "bin" / "python3"

HTTP_PROXY = os.getenv("HTTP_PROXY", "http://127.0.0.1:10808")
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "http://127.0.0.1:10808")

GOOGLE_API_KEYS = os.getenv("GOOGLE_API_KEYS", "")
MODEL_NAME = "gemini-3-flash-preview"

DEFAULT_STYLE = {
    "font_size_main": 52,
    "main_bottom": 12.0,
    "font_size_sub": 32,
    "sub_bottom": 5.0,
}
