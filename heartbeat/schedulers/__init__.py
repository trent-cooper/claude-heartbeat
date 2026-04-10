from heartbeat.schedulers.base import Scheduler
from heartbeat.schedulers.launchd import LaunchdScheduler
from heartbeat.schedulers.systemd import SystemdScheduler

SCHEDULERS = {
    "launchd": LaunchdScheduler,
    "systemd": SystemdScheduler,
}


def get_scheduler() -> Scheduler:
    """Get the appropriate scheduler for the current platform."""
    import platform
    system = platform.system()
    if system == "Darwin":
        return LaunchdScheduler()
    if system == "Linux":
        return SystemdScheduler()
    raise RuntimeError(f"Unsupported platform: {system}. Supported: macOS (launchd), Linux (systemd).")
