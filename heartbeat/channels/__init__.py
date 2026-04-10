from heartbeat.channels.file import FileChannel


def get_channel(config: dict) -> FileChannel:
    """Create a file channel instance from config."""
    return FileChannel(config)
