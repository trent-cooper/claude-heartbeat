"""Abstract base class for OS schedulers."""

from abc import ABC, abstractmethod


class Scheduler(ABC):
    """Base class for OS-level task schedulers."""

    @abstractmethod
    def install(self, task_name: str, schedule: str, command: list[str]) -> tuple[bool, str]:
        """Install a scheduled task. Returns (success, detail)."""
        ...

    @abstractmethod
    def uninstall(self, task_name: str) -> tuple[bool, str]:
        """Remove a scheduled task. Returns (success, detail)."""
        ...

    @abstractmethod
    def uninstall_all(self) -> tuple[bool, str]:
        """Remove all claude-heartbeat scheduled tasks. Returns (success, detail)."""
        ...

    @abstractmethod
    def status(self) -> list[dict]:
        """List installed tasks and their status."""
        ...

    @abstractmethod
    def is_installed(self, task_name: str) -> bool:
        """Check if a specific task is installed."""
        ...
