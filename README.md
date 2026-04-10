# claude-heartbeat

Persistent OS-level scheduling for Claude Code CLI sessions via a file-watching MCP channel.

## The Problem

Claude Code's built-in scheduling (`CronCreate`, `/schedule`) is session-scoped: it dies on restart and expires after 7 days. Worse, triggers fire at unreliable times -- up to 30 minutes late due to jitter and idle-only execution constraints. There is no built-in mechanism for an external process to wake a running CLI session on a precise schedule.

## How It Works

claude-heartbeat uses the OS scheduler (launchd on macOS, systemd user timers on Linux) to write trigger files at exact times. A lightweight MCP channel server watches for those files and delivers them to the Claude Code session as channel events.

```
OS scheduler (launchd / systemd)
  -> heartbeat fire <task>          (writes .trigger file)
    -> ~/.claude-heartbeat/inbox/   (filesystem)
      -> MCP channel server         (watches directory)
        -> Claude Code session      (receives channel event)
```

No external services. No network calls. Just the filesystem.

## Installation

### 1. Install the CLI

```bash
cd claude-heartbeat
pip install -e .
```

### 2. Install the channel server dependencies

```bash
cd channel
npm install
```

### 3. Register the MCP server

Add to `~/.claude.json` under the project that should receive heartbeat triggers:

```json
{
  "mcpServers": {
    "heartbeat": {
      "type": "stdio",
      "command": "bun",
      "args": ["/path/to/claude-heartbeat/channel/server.ts"]
    }
  }
}
```

### 4. Launch Claude Code with the channel

```bash
claude --channels --dangerously-load-development-channels server:heartbeat
```

The `--dangerously-load-development-channels` flag is required for custom (non-marketplace) channels.

## Quick Start

```bash
# Create default config
heartbeat init

# Add a task
heartbeat add morning_briefing \
  --schedule "57 7 * * *" \
  --message "[HEARTBEAT:morning_briefing]"

# Test it (writes a trigger file immediately)
heartbeat test morning_briefing

# Register with the OS scheduler (launchd on macOS, systemd on Linux)
heartbeat install

# Verify
heartbeat status
heartbeat list
```

## Configuration

Config lives at `~/.claude-heartbeat/config.yaml`:

```yaml
channel:
  type: file
  inbox_dir: "~/.claude-heartbeat/inbox"

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

### Config Reference

| Key | Description | Default |
|---|---|---|
| `channel.type` | Channel type | `file` |
| `channel.inbox_dir` | Directory for trigger files | `~/.claude-heartbeat/inbox` |
| `tasks.<name>.schedule` | Cron expression (5-field) | required |
| `tasks.<name>.message` | Message content delivered to session | required |
| `tasks.<name>.enabled` | Whether the task is active | `true` |

Values support `${ENV_VAR}` expansion.

## CLI Reference

| Command | Description |
|---|---|
| `heartbeat init` | Create config directory and default config file |
| `heartbeat add <name> -s <cron> -m <msg>` | Add a scheduled task |
| `heartbeat remove <name>` | Remove a task from config and scheduler |
| `heartbeat list` | Show all tasks with schedule, status, and last trigger time |
| `heartbeat install` | Register enabled tasks with the OS scheduler |
| `heartbeat uninstall` | Remove all scheduled tasks from the OS scheduler |
| `heartbeat test <name>` | Write a test trigger file immediately |
| `heartbeat fire <name>` | Fire a trigger (called by launchd, not by you) |
| `heartbeat status` | Show installed scheduler job status |
| `heartbeat logs [name] [-n N]` | Show recent trigger history |

## Cron Expressions

Standard 5-field format: `minute hour day-of-month month day-of-week`

```
57 7 * * *      daily at 7:57 AM
3 18 * * 0      Sundays at 6:03 PM
0 */6 * * *     every 6 hours
0 9 * * 1-5     weekdays at 9:00 AM
```

Day of week: 0 = Sunday, 6 = Saturday.

## How the Channel Works

The MCP channel server (`channel/server.ts`) watches `~/.claude-heartbeat/inbox/` for `.trigger` files using `fs.watch` with a 30-second polling fallback. When a trigger file appears:

1. Reads the file content
2. Emits a `notifications/claude/channel` MCP notification
3. Deletes the trigger file

Messages arrive in the Claude Code session as:

```xml
<channel source="heartbeat" task="morning_briefing" ts="...">
[HEARTBEAT:morning_briefing]
</channel>
```

The session can then act on the trigger -- run a daily briefing, generate a report, check on tasks, or anything else defined in CLAUDE.md.

## Supported Platforms

- **macOS** (launchd) -- fully supported
- **Linux** (systemd user timers) -- fully supported

## Requirements

- Python 3.10+
- [Bun](https://bun.sh) (for the MCP channel server)
- macOS (launchd) or Linux (systemd with user session support)
- Claude Code CLI with channels support

## License

MIT
