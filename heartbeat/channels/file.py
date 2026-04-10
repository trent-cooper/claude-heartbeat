"""File-based channel implementation for heartbeat triggers."""

import os
from datetime import datetime
from pathlib import Path

from heartbeat.channels.base import Channel


class FileChannel(Channel):
    """Write trigger files to a watched inbox directory.

    The claude-heartbeat MCP channel server watches this directory
    and delivers trigger messages to the Claude Code session.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        default_inbox = os.path.join(
            os.path.expanduser("~"), ".claude-heartbeat", "inbox"
        )
        self.inbox_dir = config.get("inbox_dir", default_inbox)

    def validate_config(self) -> tuple[bool, str]:
        if not self.inbox_dir:
            return False, "inbox_dir is required"
        return True, ""

    def send(self, message: str, task_name: str = "trigger") -> tuple[bool, str]:
        valid, err = self.validate_config()
        if not valid:
            return False, f"Invalid config: {err}"

        try:
            inbox = Path(self.inbox_dir)
            inbox.mkdir(parents=True, exist_ok=True)

            # Use timestamp + task name for unique, sorted filenames
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            trigger_file = inbox / f"{ts}_{task_name}.trigger"
            trigger_file.write_text(message)

            return True, "Trigger file written"

        except Exception as e:
            return False, f"Write failed: {e}"
