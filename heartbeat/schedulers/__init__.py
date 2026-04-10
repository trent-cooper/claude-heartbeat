from heartbeat.schedulers.base import Scheduler
from heartbeat.schedulers.launchd import LaunchdScheduler

SCHEDULERS = {
    "launchd": LaunchdScheduler,
}


def get_scheduler() -> Scheduler:
    """Get the appropriate scheduler for the current platform."""
    import platform
    if platform.system() == "Darwin":
        return LaunchdScheduler()
    raise RuntimeError(f"Unsupported platform: {platform.system()}. Only macOS (launchd) is currently supported.")
