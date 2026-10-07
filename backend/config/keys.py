import os
import random
from dotenv import load_dotenv, dotenv_values
from config.settings import ENV_FILE

load_dotenv(ENV_FILE)


def read_google_api_keys():
    """.env 文件优先；文件里没有（或没有这个文件）再看进程环境。

    Web 界面「系统设置」改 key 写的是 .env 文件（Docker：userdata/.env）。mover 容器的环境变量是
    容器创建时从同一个文件注入的，之后不会再变：如果环境优先，Web 上换了 key，自动搬运和
    「生成并投稿」用的还是旧 key，要重建容器才生效。文件优先之后两个进程读的是同一个文件，
    改完下一个视频就用上新 key（每个视频都是新起的 entry_cli 进程）。
    """
    if ENV_FILE.is_file():
        raw = dotenv_values(ENV_FILE).get("GOOGLE_API_KEYS") or ""
        if raw.strip():
            return raw
    return os.getenv("GOOGLE_API_KEYS", "")


class GoogleApiRotationManager:
    def __init__(self):
        raw_api_keys_string = read_google_api_keys()
        self.active_api_keys = [key.strip() for key in raw_api_keys_string.split(",") if key.strip()]
        self.next_key_index = 0

    def get_next_available_api_key(self):
        if not self.active_api_keys:
            raise EnvironmentError("No Google API keys found in the system environment configuration.")
            
        current_api_key = self.active_api_keys[self.next_key_index]
        self.next_key_index = (self.next_key_index + 1) % len(self.active_api_keys)
        return current_api_key

    def get_randomly_selected_api_key(self):
        return random.choice(self.active_api_keys)

key_manager = GoogleApiRotationManager()
