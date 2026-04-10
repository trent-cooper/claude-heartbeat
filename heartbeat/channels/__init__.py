from heartbeat.channels.base import Channel
from heartbeat.channels.telegram import TelegramChannel
from heartbeat.channels.file import FileChannel

CHANNELS = {
    "telegram": TelegramChannel,
    "file": FileChannel,
}


def get_channel(config: dict) -> Channel:
    """Create a channel instance from config."""
    channel_type = config.get("type", "telegram")
    if channel_type not in CHANNELS:
        raise ValueError(f"Unknown channel type: {channel_type}")
    return CHANNELS[channel_type](config)
