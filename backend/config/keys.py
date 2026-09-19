import os
import random
from dotenv import load_dotenv, dotenv_values
from config.settings import ENV_FILE

load_dotenv(ENV_FILE)


def read_google_api_keys():
    """进程环境优先；环境里是空串时再看 .env 文件。

    Docker 下 compose 会把 userdata/.env 的 GOOGLE_API_KEYS 注入成环境变量，哪怕它是空的；
    load_dotenv 不覆盖已存在的变量，于是用户事后在 Web 界面或文件里填的 key 只有重建容器才能
    被看到。这里补一层文件回退，让 restart（不重建）也能读到新值。
    """
    raw = os.getenv("GOOGLE_API_KEYS", "")
    if not raw.strip():
        raw = (dotenv_values(ENV_FILE).get("GOOGLE_API_KEYS") or "") if ENV_FILE.is_file() else ""
    return raw


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
