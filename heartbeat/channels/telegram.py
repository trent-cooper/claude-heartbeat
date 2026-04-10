"""Telegram channel implementation using Telethon (user API)."""

from heartbeat.channels.base import Channel


class TelegramChannel(Channel):
    """Send messages via Telegram user API (Telethon).

    Uses a pre-authenticated Telethon session to send messages as the user,
    not as a bot. This is necessary because Telegram bots cannot receive
    messages from other bots — so a bot-based trigger would never reach
    the Claude Code session's bot-based channel plugin.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_id = config.get("api_id", "")
        self.api_hash = config.get("api_hash", "")
        self.chat_id = config.get("chat_id", "")
        self.session_path = config.get("session_path", "")

    def validate_config(self) -> tuple[bool, str]:
        if not self.api_id:
            return False, "api_id is required"
        if not self.api_hash:
            return False, "api_hash is required"
        if not self.chat_id:
            return False, "chat_id is required"
        if not self.session_path:
            return False, "session_path is required"
        return True, ""

    def send(self, message: str) -> tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, f"Invalid config: {err}"

        try:
            from telethon.sync import TelegramClient

            client = TelegramClient(
                self.session_path, int(self.api_id), self.api_hash
            )
            client.connect()

            if not client.is_user_authorized():
                client.disconnect()
                return False, "Telethon session not authorized. Run 'heartbeat init' to authenticate."

            client.send_message(int(self.chat_id), message)
            client.disconnect()
            return True, "Message sent"

        except Exception as e:
            return False, f"Send failed: {e}"
