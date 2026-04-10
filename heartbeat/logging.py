"""Simple trigger history logging."""

from datetime import datetime
from pathlib import Path

from heartbeat.config import LOG_FILE, ensure_config_dir


def log_trigger(task_name: str, status: str, message: str) -> None:
    """Append a trigger event to the log file."""
    ensure_config_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} | {task_name} | {status} | {message}\n"
    with open(LOG_FILE, "a") as f:
        f.write(line)


def read_logs(task_name: str | None = None, limit: int = 25) -> list[str]:
    """Read recent log entries, optionally filtered by task name."""
    if not LOG_FILE.exists():
        return []

    with open(LOG_FILE) as f:
        lines = f.readlines()

    if task_name:
        lines = [l for l in lines if f"| {task_name} |" in l]

    return [l.rstrip() for l in lines[-limit:]]
