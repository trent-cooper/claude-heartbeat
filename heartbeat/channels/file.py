"""File-based channel for delivering heartbeat triggers."""

import os
from datetime import datetime
from pathlib import Path


class FileChannel:
    """Write trigger files to a watched inbox directory.

    The MCP channel server watches this directory and delivers
    trigger messages to the Claude Code session.
    """

    def __init__(self, config: dict):
        default_inbox = os.path.join(
            os.path.expanduser("~"), ".claude-heartbeat", "inbox"
        )
        self.inbox_dir = config.get("inbox_dir", default_inbox)

    def send(self, message: str, task_name: str = "trigger") -> tuple[bool, str]:
        """Write a trigger file to the inbox directory.

        Returns (success, detail_message).
        """
        try:
            inbox = Path(self.inbox_dir)
            inbox.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            trigger_file = inbox / f"{ts}_{task_name}.trigger"
            trigger_file.write_text(message)

            return True, "Trigger file written"

        except Exception as e:
            return False, f"Write failed: {e}"
