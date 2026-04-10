# claude-heartbeat

Persistent OS-level scheduling for Claude Code CLI sessions.

## The Problem

Claude Code CLI's built-in scheduling (`CronCreate`, `/loop`) is session-only — it dies on restart and expires after 7 days. Desktop scheduled tasks require the Desktop app. Cloud scheduled tasks can't access local files or MCP servers. There's no built-in way for an external process to trigger a running CLI session.

## The Solution

claude-heartbeat bridges macOS launchd (the OS scheduler) to a running Claude Code session via a lightweight MCP channel that watches the filesystem. No external services, no network calls, no Telegram bots — just files.

### How It Works

```
launchd (OS scheduler)
  → heartbeat fire <task>        (writes .trigger file)
    → ~/.claude-heartbeat/inbox/   (filesystem)
      → MCP channel server         (watches directory)
        → Claude Code session      (receives channel notification)
```

1. You define tasks with cron schedules in `~/.claude-heartbeat/config.yaml`
2. `heartbeat install` creates macOS LaunchAgent plists for each task
3. At the scheduled time, launchd runs `heartbeat fire <task_name>`
4. The fire command writes a `.trigger` file to the inbox directory
5. The MCP channel server detects the file and delivers it to the Claude Code session as a `<channel source="heartbeat">` event
6. Claude Code processes the trigger and executes the task

## Installation

### 1. Install the CLI

```bash
cd claude-heartbeat
pip install -e .
```

### 2. Install the MCP channel server dependencies

```bash
cd channel
npm install
```

### 3. Register the channel as an MCP server

Add to your project's MCP config in `~/.claude.json` under the relevant project:

```json
"mcpServers": {
  "heartbeat": {
    "type": "stdio",
    "command": "bun",
    "args": ["/path/to/claude-heartbeat/channel/server.ts"]
  }
}
```

### 4. Launch Claude Code with the channel

```bash
claude --channels server:heartbeat --dangerously-load-development-channels
```

The `--dangerously-load-development-channels` flag is required for custom (non-marketplace) channels.

## Quick Start

```bash
# Create config at ~/.claude-heartbeat/config.yaml
heartbeat init

# Add a task
heartbeat add morning_briefing \
  --schedule "57 7 * * *" \
  --message "[HEARTBEAT:morning_briefing]"

# Test it (writes trigger file immediately)
heartbeat test morning_briefing

# Register with macOS launchd
heartbeat install

# Verify
heartbeat status
heartbeat list
```

## Config File

Located at `~/.claude-heartbeat/config.yaml`:

```yaml
channel:
  type: file
  inbox_dir: "~/.claude-heartbeat/inbox"

tasks:
  morning_briefing:
    schedule: "57 7 * * *"
    message: "[HEARTBEAT:morning_briefing]"
    enabled: true

  evening_checkin:
    schedule: "3 19 * * *"
    message: "[HEARTBEAT:evening_checkin]"
    enabled: true

  weekly_review:
    schedule: "3 18 * * 0"
    message: "[HEARTBEAT:weekly_review]"
    enabled: true
```

## CLI Commands

| Command | Description |
|---|---|
| `heartbeat init` | Interactive setup — creates config directory and file |
| `heartbeat add <name> -s "cron" -m "msg"` | Add a scheduled task |
| `heartbeat remove <name>` | Remove a task from config and scheduler |
| `heartbeat list` | Show all tasks with schedule, status, last trigger |
| `heartbeat install` | Register enabled tasks with macOS launchd |
| `heartbeat uninstall` | Remove all LaunchAgent plists |
| `heartbeat test <name>` | Send a test trigger immediately |
| `heartbeat fire <name>` | Fire a trigger (called by launchd, not you) |
| `heartbeat status` | Show installed launchd status |
| `heartbeat logs [name]` | Show recent trigger history |

## Cron Expressions

Standard 5-field: `minute hour day-of-month month day-of-week`

- `57 7 * * *` — daily at 7:57 AM
- `3 18 * * 0` — Sundays at 6:03 PM
- `0 */6 * * *` — every 6 hours
- `0 9 * * 1-5` — weekdays at 9 AM

Day of week: 0 = Sunday, 6 = Saturday.

## Channel Delivery

The MCP channel server (`channel/server.ts`) watches `~/.claude-heartbeat/inbox/` for `.trigger` files using `fs.watch` with a 30-second polling fallback. When a file appears:

1. Reads the file content
2. Emits a `notifications/claude/channel` MCP notification
3. Deletes the trigger file

Messages arrive in Claude Code as:

```
<channel source="heartbeat" task="morning_briefing" ts="...">
[HEARTBEAT:morning_briefing]
</channel>
```

## Alternative: Telegram Channel

A Telegram channel backend is also included for setups where file-based triggering isn't suitable. See `heartbeat/channels/telegram.py`. Note: Telegram bots cannot receive messages from other bots, so the Telegram approach requires using the Telethon user API.

## Supported Platforms

- **macOS** (launchd) — supported
- **Linux** (systemd timers / cron) — planned

## Requirements

- Python 3.10+
- Node.js / Bun (for the MCP channel server)
- macOS (for launchd scheduling)
- Claude Code CLI with channels support (v2.1.80+)
