# claude-heartbeat

Persistent OS-level scheduling for Claude Code CLI sessions.

## The Problem

Claude Code CLI's built-in `CronCreate` is session-only and expires after 7 days. There's no way for an external process to trigger a running Claude Code session. This tool fills that gap by bridging OS schedulers (macOS launchd) to Claude Code via messaging channels (Telegram).

## How It Works

1. You define tasks with cron schedules and trigger messages
2. `heartbeat install` creates macOS LaunchAgent plists for each task
3. At the scheduled time, launchd runs `heartbeat fire <task_name>`
4. The fire command sends the trigger message to your Telegram bot
5. Claude Code (listening on Telegram) receives the message and acts on it

## Installation

```bash
pip install -e .
```

This installs the `heartbeat` command.

## Quick Start

```bash
# Interactive setup — creates ~/.claude-heartbeat/config.yaml
heartbeat init

# Add a task
heartbeat add morning_briefing \
  --schedule "57 7 * * *" \
  --message "[HEARTBEAT:morning_briefing]"

# Test it (sends immediately)
heartbeat test morning_briefing

# Register with macOS launchd
heartbeat install

# Verify
heartbeat status
```

## Config File

Located at `~/.claude-heartbeat/config.yaml`:

```yaml
channel:
  type: telegram
  bot_token: "${HEARTBEAT_BOT_TOKEN}"  # env var reference
  chat_id: "12345"

tasks:
  morning_briefing:
    schedule: "57 7 * * *"
    message: "[HEARTBEAT:morning_briefing]"
    enabled: true

  weekly_review:
    schedule: "3 18 * * 0"
    message: "[HEARTBEAT:weekly_review]"
    enabled: true
```

Environment variables in `${VAR_NAME}` format are expanded at runtime. Set `HEARTBEAT_BOT_TOKEN` in your shell profile.

## CLI Commands

| Command | Description |
|---|---|
| `heartbeat init` | Interactive setup — creates config directory and file |
| `heartbeat add <name> -s "cron" -m "message"` | Add a scheduled task |
| `heartbeat remove <name>` | Remove a task from config and scheduler |
| `heartbeat list` | Show all tasks with schedule, status, last trigger |
| `heartbeat install` | Register enabled tasks with macOS launchd |
| `heartbeat uninstall` | Remove all LaunchAgent plists |
| `heartbeat test <name>` | Send a test trigger message immediately |
| `heartbeat fire <name>` | Fire a trigger (called by launchd, not you) |
| `heartbeat status` | Show which tasks are installed in launchd |
| `heartbeat logs [name]` | Show recent trigger history |

### Cron Expressions

Standard 5-field cron: `minute hour day-of-month month day-of-week`

- `57 7 * * *` — every day at 7:57 AM
- `3 18 * * 0` — Sundays at 6:03 PM
- `0 */6 * * *` — every 6 hours
- `0 9 * * 1-5` — weekdays at 9 AM

Day of week: 0 = Sunday, 6 = Saturday.

## Logging

Trigger history is logged to `~/.claude-heartbeat/heartbeat.log`:

```
2026-04-10 07:57:01 | morning_briefing | ok | Message sent
2026-04-10 18:03:01 | weekly_review | ok | Message sent
```

## Supported Platforms

- **macOS** (launchd) — supported
- **Linux** (systemd timers) — planned

## Supported Channels

- **Telegram** — supported
- **Discord** — planned
- **Slack** — planned
