"""Telegram channel implementation using Bot API."""

import requests

from heartbeat.channels.base import Channel


class TelegramChannel(Channel):
    """Send messages via Telegram Bot API."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, config: dict):
        super().__init__(config)
        self.bot_token = config.get("bot_token", "")
        self.chat_id = config.get("chat_id", "")

    def validate_config(self) -> tuple[bool, str]:
        if not self.bot_token:
            return False, "bot_token is required"
        if not self.chat_id:
            return False, "chat_id is required"
        return True, ""

    def send(self, message: str) -> tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, f"Invalid config: {err}"

        url = f"{self.API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_notification": True,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("ok"):
                return True, "Message sent"
            else:
                return False, f"Telegram API error: {data.get('description', 'unknown')}"
        except requests.RequestException as e:
            return False, f"Request failed: {e}"
