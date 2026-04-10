"""Linux systemd user timer scheduler implementation."""

import shutil
import subprocess
from pathlib import Path

from heartbeat.schedulers.base import Scheduler


SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PREFIX = "claude-heartbeat"

# Cron day-of-week (0=Sun) to systemd abbreviation
DOW_MAP = {
    0: "Sun",
    1: "Mon",
    2: "Tue",
    3: "Wed",
    4: "Thu",
    5: "Fri",
    6: "Sat",
}


def _convert_field(field: str, low: int, high: int) -> str | None:
    """Convert a single cron field to systemd OnCalendar syntax.

    Returns None for wildcard (*), meaning use '*' in the output.
    """
    if field == "*":
        return None

    if field.startswith("*/"):
        step = int(field[2:])
        return f"{low}/{step}"

    parts = []
    for part in field.split(","):
        if "-" in part:
            start, end = part.split("-", 1)
            parts.append(f"{start}..{end}")
        else:
            parts.append(part)
    return ",".join(parts)


def cron_to_oncalendar(cron_expr: str) -> str:
    """Convert a cron expression to a systemd OnCalendar value.

    Cron format: minute hour day-of-month month day-of-week
    Systemd OnCalendar: DayOfWeek Year-Month-Day Hour:Minute:Second

    Examples:
        '57 7 * * *'   -> '*-*-* 07:57:00'
        '3 18 * * 0'   -> 'Sun *-*-* 18:03:00'
        '0 9 * * 1-5'  -> 'Mon..Fri *-*-* 09:00:00'
        '0 */6 * * *'  -> '*-*-* 00/6:00:00'
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {cron_expr}")

    minute_raw, hour_raw, dom_raw, month_raw, dow_raw = parts

    # Convert day-of-week
    dow_prefix = ""
    if dow_raw != "*":
        dow_parts = []
        for part in dow_raw.split(","):
            if "-" in part:
                start, end = part.split("-", 1)
                dow_parts.append(f"{DOW_MAP[int(start)]}..{DOW_MAP[int(end)]}")
            else:
                dow_parts.append(DOW_MAP[int(part)])
        dow_prefix = ",".join(dow_parts) + " "

    # Convert date fields
    month_str = _convert_field(month_raw, 1, 12) or "*"
    dom_str = _convert_field(dom_raw, 1, 31) or "*"

    # Convert time fields
    minute_conv = _convert_field(minute_raw, 0, 59)
    hour_conv = _convert_field(hour_raw, 0, 23)

    # Format time with zero-padding for simple numeric values
    if minute_conv is None:
        minute_str = "*"
    elif minute_conv.isdigit():
        minute_str = minute_conv.zfill(2)
    else:
        minute_str = minute_conv

    if hour_conv is None:
        hour_str = "*"
    elif hour_conv.isdigit():
        hour_str = hour_conv.zfill(2)
    else:
        hour_str = hour_conv

    return f"{dow_prefix}*-{month_str}-{dom_str} {hour_str}:{minute_str}:00"


class SystemdScheduler(Scheduler):
    """Linux systemd user timer scheduler."""

    def _service_name(self, task_name: str) -> str:
        return f"{UNIT_PREFIX}-{task_name}.service"

    def _timer_name(self, task_name: str) -> str:
        return f"{UNIT_PREFIX}-{task_name}.timer"

    def _service_path(self, task_name: str) -> Path:
        return SYSTEMD_USER_DIR / self._service_name(task_name)

    def _timer_path(self, task_name: str) -> Path:
        return SYSTEMD_USER_DIR / self._timer_name(task_name)

    def _find_heartbeat_exe(self) -> str:
        """Find the full path to the heartbeat executable."""
        exe = shutil.which("heartbeat")
        if exe:
            return exe
        for candidate in [
            Path.home() / ".local" / "bin" / "heartbeat",
            Path("/usr/local/bin/heartbeat"),
        ]:
            if candidate.exists():
                return str(candidate)
        raise RuntimeError(
            "Cannot find 'heartbeat' executable. Make sure it's installed and on your PATH."
        )

    def _daemon_reload(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            text=True,
        )

    def install(self, task_name: str, schedule: str, command: list[str]) -> tuple[bool, str]:
        SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)

        service_path = self._service_path(task_name)
        timer_path = self._timer_path(task_name)
        timer_name = self._timer_name(task_name)
        oncalendar = cron_to_oncalendar(schedule)

        # Disable existing timer if present
        if timer_path.exists():
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", timer_name],
                capture_output=True,
            )

        # Write service unit
        exec_start = " ".join(command)
        service_content = f"""\
[Unit]
Description=claude-heartbeat task: {task_name}

[Service]
Type=oneshot
ExecStart={exec_start}
"""
        service_path.write_text(service_content)

        # Write timer unit
        timer_content = f"""\
[Unit]
Description=claude-heartbeat timer: {task_name}

[Timer]
OnCalendar={oncalendar}
Persistent=true

[Install]
WantedBy=timers.target
"""
        timer_path.write_text(timer_content)

        # Reload and enable
        self._daemon_reload()

        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", timer_name],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return False, f"Failed to enable timer: {result.stderr.strip()}"
        return True, f"Installed and enabled {timer_name} ({oncalendar})"

    def uninstall(self, task_name: str) -> tuple[bool, str]:
        timer_path = self._timer_path(task_name)
        service_path = self._service_path(task_name)
        timer_name = self._timer_name(task_name)

        if not timer_path.exists() and not service_path.exists():
            return False, f"No unit files found for {task_name}"

        subprocess.run(
            ["systemctl", "--user", "disable", "--now", timer_name],
            capture_output=True,
        )

        removed = []
        for path in [timer_path, service_path]:
            if path.exists():
                path.unlink()
                removed.append(path.name)

        self._daemon_reload()
        return True, f"Disabled and removed: {', '.join(removed)}"

    def uninstall_all(self) -> tuple[bool, str]:
        removed = []
        for timer in SYSTEMD_USER_DIR.glob(f"{UNIT_PREFIX}-*.timer"):
            timer_name = timer.name
            task_name = timer.stem.replace(f"{UNIT_PREFIX}-", "", 1)

            subprocess.run(
                ["systemctl", "--user", "disable", "--now", timer_name],
                capture_output=True,
            )
            timer.unlink()
            removed.append(timer_name)

            service_path = self._service_path(task_name)
            if service_path.exists():
                service_path.unlink()
                removed.append(service_path.name)

        if removed:
            self._daemon_reload()

        if not removed:
            return True, "No tasks were installed"
        return True, f"Removed {len(removed)} unit file(s): {', '.join(removed)}"

    def status(self) -> list[dict]:
        results = []
        for timer in sorted(SYSTEMD_USER_DIR.glob(f"{UNIT_PREFIX}-*.timer")):
            task_name = timer.stem.replace(f"{UNIT_PREFIX}-", "", 1)

            check = subprocess.run(
                ["systemctl", "--user", "is-active", timer.name],
                capture_output=True,
                text=True,
            )
            active = check.stdout.strip() == "active"

            results.append({
                "task_name": task_name,
                "timer": str(timer),
                "service": str(self._service_path(task_name)),
                "active": active,
            })
        return results

    def is_installed(self, task_name: str) -> bool:
        return self._timer_path(task_name).exists()
