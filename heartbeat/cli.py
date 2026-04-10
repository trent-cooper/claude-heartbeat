"""Click-based CLI for claude-heartbeat."""

import shutil
import sys

import click

from heartbeat.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    load_config,
    save_config,
    get_tasks,
    ensure_config_dir,
)
from heartbeat.channels import get_channel
from heartbeat.schedulers import get_scheduler
from heartbeat.logging import log_trigger, read_logs


@click.group()
def cli():
    """claude-heartbeat: Persistent OS-level scheduling for Claude Code."""
    pass


@cli.command()
def init():
    """Create config directory and default config file."""
    if CONFIG_FILE.exists():
        if not click.confirm(f"Config already exists at {CONFIG_FILE}. Overwrite?"):
            click.echo("Aborted.")
            return

    config = {
        "channel": {
            "type": "file",
            "inbox_dir": str(CONFIG_DIR / "inbox"),
        },
        "tasks": {},
    }

    save_config(config)
    click.echo(f"Config saved to {CONFIG_FILE}")
    click.echo("Add tasks with: heartbeat add <name> --schedule '...' --message '...'")


@cli.command()
@click.argument("name")
@click.option("--schedule", "-s", required=True, help="Cron expression (5-field)")
@click.option("--message", "-m", required=True, help="Message to send when triggered")
@click.option("--enabled/--disabled", default=True, help="Whether task is enabled")
def add(name, schedule, message, enabled):
    """Add a scheduled task."""
    config = load_config(resolve_env=False)
    if "tasks" not in config:
        config["tasks"] = {}

    config["tasks"][name] = {
        "schedule": schedule,
        "message": message,
        "enabled": enabled,
    }

    save_config(config)
    click.echo(f"Added task '{name}' with schedule '{schedule}'")
    click.echo("Run 'heartbeat install' to register with OS scheduler.")


@cli.command()
@click.argument("name")
def remove(name):
    """Remove a scheduled task."""
    config = load_config(resolve_env=False)
    tasks = config.get("tasks", {})

    if name not in tasks:
        click.echo(f"Task '{name}' not found.")
        sys.exit(1)

    del tasks[name]
    save_config(config)

    # Also uninstall from scheduler if present
    try:
        scheduler = get_scheduler()
        if scheduler.is_installed(name):
            scheduler.uninstall(name)
            click.echo(f"Removed task '{name}' from config and OS scheduler.")
            return
    except RuntimeError:
        pass

    click.echo(f"Removed task '{name}' from config.")


@cli.command("list")
def list_tasks():
    """Show all configured tasks."""
    try:
        config = load_config(resolve_env=False)
    except FileNotFoundError as e:
        click.echo(str(e))
        sys.exit(1)

    tasks = get_tasks(config)
    if not tasks:
        click.echo("No tasks configured. Add one with: heartbeat add <name> ...")
        return

    # Check scheduler status
    try:
        scheduler = get_scheduler()
        installed = {s["task_name"] for s in scheduler.status()}
    except RuntimeError:
        installed = set()

    # Check logs for last trigger
    all_logs = read_logs(limit=1000)
    last_triggers = {}
    for line in all_logs:
        parts = line.split(" | ")
        if len(parts) >= 3:
            task = parts[1].strip()
            timestamp = parts[0].strip()
            last_triggers[task] = timestamp

    for name, task in tasks.items():
        status_parts = []
        if task.get("enabled", True):
            status_parts.append("enabled")
        else:
            status_parts.append("disabled")
        if name in installed:
            status_parts.append("installed")
        else:
            status_parts.append("not installed")

        last = last_triggers.get(name, "never")
        click.echo(f"  {name}")
        click.echo(f"    Schedule: {task.get('schedule', '?')}")
        click.echo(f"    Message:  {task.get('message', '?')}")
        click.echo(f"    Status:   {', '.join(status_parts)}")
        click.echo(f"    Last run: {last}")
        click.echo()


@cli.command()
def install():
    """Register all enabled tasks with the OS scheduler."""
    config = load_config(resolve_env=False)
    tasks = get_tasks(config)

    if not tasks:
        click.echo("No tasks to install.")
        return

    scheduler = get_scheduler()

    # Find the heartbeat executable
    exe = shutil.which("heartbeat")
    if not exe:
        click.echo("Error: 'heartbeat' executable not found on PATH.")
        click.echo("Make sure the package is installed: pip install -e .")
        sys.exit(1)

    installed_count = 0
    for name, task in tasks.items():
        if not task.get("enabled", True):
            click.echo(f"  Skipping '{name}' (disabled)")
            continue

        schedule = task.get("schedule")
        if not schedule:
            click.echo(f"  Skipping '{name}' (no schedule)")
            continue

        command = [exe, "fire", name]
        ok, detail = scheduler.install(name, schedule, command)
        if ok:
            click.echo(f"  Installed '{name}': {detail}")
            installed_count += 1
        else:
            click.echo(f"  Failed '{name}': {detail}")

    click.echo(f"\n{installed_count} task(s) installed.")


@cli.command()
def uninstall():
    """Remove all LaunchAgent plists."""
    scheduler = get_scheduler()
    ok, detail = scheduler.uninstall_all()
    click.echo(detail)


@cli.command()
@click.argument("name")
def test(name):
    """Send a test trigger message immediately."""
    config = load_config(resolve_env=True)
    tasks = get_tasks(config)

    if name not in tasks:
        click.echo(f"Task '{name}' not found in config.")
        sys.exit(1)

    task = tasks[name]
    message = task.get("message", f"[HEARTBEAT:{name}]")

    channel = get_channel(config["channel"])
    click.echo(f"Sending test message for '{name}'...")
    ok, detail = channel.send(f"[TEST] {message}")

    if ok:
        click.echo(f"Success: {detail}")
        log_trigger(name, "test_ok", detail)
    else:
        click.echo(f"Failed: {detail}")
        log_trigger(name, "test_fail", detail)
        sys.exit(1)


@cli.command()
@click.argument("name")
def fire(name):
    """Fire a task trigger. Called by the OS scheduler."""
    try:
        config = load_config(resolve_env=True)
    except Exception as e:
        log_trigger(name, "error", f"Config load failed: {e}")
        sys.exit(1)

    tasks = get_tasks(config)
    if name not in tasks:
        log_trigger(name, "error", f"Task '{name}' not found in config")
        sys.exit(1)

    task = tasks[name]
    if not task.get("enabled", True):
        log_trigger(name, "skipped", "Task is disabled")
        return

    message = task.get("message", f"[HEARTBEAT:{name}]")

    try:
        channel = get_channel(config["channel"])
        ok, detail = channel.send(message, task_name=name)
    except Exception as e:
        log_trigger(name, "error", str(e))
        sys.exit(1)

    if ok:
        log_trigger(name, "ok", detail)
    else:
        log_trigger(name, "fail", detail)
        sys.exit(1)


@cli.command()
def status():
    """Show which tasks are installed in the OS scheduler."""
    scheduler = get_scheduler()
    tasks = scheduler.status()

    if not tasks:
        click.echo("No tasks installed in the OS scheduler.")
        return

    for t in tasks:
        loaded_str = "loaded" if t["loaded"] else "not loaded"
        click.echo(f"  {t['task_name']}: {loaded_str}")
        click.echo(f"    Plist: {t['plist']}")
        click.echo()


@cli.command()
@click.argument("name", required=False)
@click.option("--limit", "-n", default=25, help="Number of log entries to show")
def logs(name, limit):
    """Show recent trigger history."""
    entries = read_logs(task_name=name, limit=limit)
    if not entries:
        click.echo("No log entries found.")
        return

    for entry in entries:
        click.echo(entry)


if __name__ == "__main__":
    cli()
