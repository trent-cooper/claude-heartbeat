"""macOS LaunchAgent scheduler implementation."""

import plistlib
import shutil
import subprocess
from pathlib import Path

from heartbeat.schedulers.base import Scheduler


LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
PLIST_PREFIX = "com.claude-heartbeat"


def cron_to_calendar(cron_expr: str) -> list[dict]:
    """Convert a cron expression to launchd StartCalendarInterval dicts.

    Cron format: minute hour day-of-month month day-of-week
    Supports: specific values, '*' (wildcard), comma-separated lists, and step values (*/N).

    Returns a list of calendar interval dicts — multiple if expansion is needed.
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {cron_expr}")

    field_names = ["Minute", "Hour", "Day", "Month", "Weekday"]
    field_ranges = [
        (0, 59),   # Minute
        (0, 23),   # Hour
        (1, 31),   # Day
        (1, 12),   # Month
        (0, 6),    # Weekday (0=Sunday)
    ]

    def expand_field(field: str, low: int, high: int) -> list[int] | None:
        """Expand a cron field to a list of values, or None for wildcard."""
        if field == "*":
            return None

        if field.startswith("*/"):
            step = int(field[2:])
            return list(range(low, high + 1, step))

        values = []
        for part in field.split(","):
            if "-" in part:
                start, end = part.split("-", 1)
                values.extend(range(int(start), int(end) + 1))
            else:
                values.append(int(part))
        return values

    expanded = []
    for i, part in enumerate(parts):
        expanded.append(expand_field(part, *field_ranges[i]))

    # Build calendar intervals. If multiple fields have multiple values,
    # we need the cartesian product for launchd.
    def build_intervals(fields, names, current=None):
        if current is None:
            current = {}
        if not fields:
            return [dict(current)] if current else [{}]

        values = fields[0]
        name = names[0]
        remaining_fields = fields[1:]
        remaining_names = names[1:]

        if values is None:
            # Wildcard — don't include this key
            return build_intervals(remaining_fields, remaining_names, current)

        results = []
        for v in values:
            next_current = dict(current)
            next_current[name] = v
            results.extend(build_intervals(remaining_fields, remaining_names, next_current))
        return results

    intervals = build_intervals(expanded, field_names)
    if not intervals or intervals == [{}]:
        # All wildcards — run every minute. Just return empty dict.
        return [{}]
    return intervals


class LaunchdScheduler(Scheduler):
    """macOS LaunchAgent scheduler."""

    def _plist_path(self, task_name: str) -> Path:
        return LAUNCH_AGENTS_DIR / f"{PLIST_PREFIX}.{task_name}.plist"

    def _label(self, task_name: str) -> str:
        return f"{PLIST_PREFIX}.{task_name}"

    def _find_heartbeat_exe(self) -> str:
        """Find the full path to the heartbeat executable."""
        exe = shutil.which("heartbeat")
        if exe:
            return exe
        # Fallback: check common locations
        for candidate in [
            Path.home() / ".local" / "bin" / "heartbeat",
            Path("/usr/local/bin/heartbeat"),
        ]:
            if candidate.exists():
                return str(candidate)
        raise RuntimeError(
            "Cannot find 'heartbeat' executable. Make sure it's installed and on your PATH."
        )

    def install(self, task_name: str, schedule: str, command: list[str]) -> tuple[bool, str]:
        LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

        plist_path = self._plist_path(task_name)
        label = self._label(task_name)

        # Unload existing if present
        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )

        calendar_intervals = cron_to_calendar(schedule)

        plist = {
            "Label": label,
            "ProgramArguments": command,
            "StartCalendarInterval": calendar_intervals if len(calendar_intervals) > 1 else calendar_intervals[0],
            "StandardOutPath": str(Path.home() / ".claude-heartbeat" / "launchd-stdout.log"),
            "StandardErrorPath": str(Path.home() / ".claude-heartbeat" / "launchd-stderr.log"),
        }

        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)

        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return False, f"launchctl load failed: {result.stderr.strip()}"
        return True, f"Installed and loaded {plist_path}"

    def uninstall(self, task_name: str) -> tuple[bool, str]:
        plist_path = self._plist_path(task_name)
        if not plist_path.exists():
            return False, f"No plist found for {task_name}"

        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )
        plist_path.unlink()
        return True, f"Unloaded and removed {plist_path}"

    def uninstall_all(self) -> tuple[bool, str]:
        removed = []
        for plist in LAUNCH_AGENTS_DIR.glob(f"{PLIST_PREFIX}.*.plist"):
            subprocess.run(
                ["launchctl", "unload", str(plist)],
                capture_output=True,
            )
            plist.unlink()
            removed.append(plist.name)

        if not removed:
            return True, "No tasks were installed"
        return True, f"Removed {len(removed)} task(s): {', '.join(removed)}"

    def status(self) -> list[dict]:
        results = []
        for plist in sorted(LAUNCH_AGENTS_DIR.glob(f"{PLIST_PREFIX}.*.plist")):
            label = plist.stem  # com.claude-heartbeat.task_name
            task_name = label.replace(f"{PLIST_PREFIX}.", "", 1)

            # Check if loaded
            check = subprocess.run(
                ["launchctl", "list", label],
                capture_output=True,
                text=True,
            )
            loaded = check.returncode == 0

            results.append({
                "task_name": task_name,
                "plist": str(plist),
                "loaded": loaded,
            })
        return results

    def is_installed(self, task_name: str) -> bool:
        return self._plist_path(task_name).exists()
