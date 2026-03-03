import os
import random
from dotenv import load_dotenv

load_dotenv()

class GoogleApiRotationManager:
    def __init__(self):
        raw_api_keys_string = os.getenv("GOOGLE_API_KEYS", "")
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
