#!/usr/bin/env bun
/**
 * Heartbeat channel for Claude Code.
 *
 * Minimal file-watching MCP channel that delivers trigger messages
 * to a running Claude Code session. External processes (launchd, cron)
 * write trigger files to the inbox directory; this server picks them
 * up and emits channel notifications.
 *
 * No external dependencies. No network calls. Pure filesystem.
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'
import { readFileSync, readdirSync, unlinkSync, mkdirSync, writeFileSync, watch } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

const STATE_DIR = process.env.HEARTBEAT_STATE_DIR ?? join(homedir(), '.claude-heartbeat')
const INBOX_DIR = join(STATE_DIR, 'inbox')
const LOG_FILE = join(STATE_DIR, 'channel.log')

// Ensure dirs exist
mkdirSync(INBOX_DIR, { recursive: true })

function log(msg: string) {
  const ts = new Date().toISOString()
  const line = `${ts} | ${msg}\n`
  process.stderr.write(`heartbeat: ${msg}\n`)
  try { writeFileSync(LOG_FILE, line, { flag: 'a' }) } catch {}
}

const mcp = new Server(
  { name: 'heartbeat', version: '1.0.0' },
  {
    capabilities: {
      tools: {},
      experimental: {
        'claude/channel': {},
      },
    },
    instructions: [
      'Messages from the heartbeat channel are scheduled triggers from the OS-level scheduler (launchd/cron).',
      'They arrive as <channel source="heartbeat"> tags containing a task identifier like [HEARTBEAT:morning_briefing].',
      '',
      'When you receive a heartbeat trigger:',
      '1. Read Tasks/heartbeat.md for the task definitions and last-run timestamps',
      '2. Execute the named task following the instructions in CLAUDE.md',
      '3. Update the last_run timestamp in heartbeat.md after completion',
      '',
      'These are automated system events, not user messages. Do not reply via the channel — send results through the appropriate output (Telegram, file writes, etc.).',
    ].join('\n'),
  },
)

// No tools needed — this is an inbound-only channel.
// Claude doesn't need to "reply" to heartbeat triggers.
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [] }))
mcp.setRequestHandler(CallToolRequestSchema, async () => {
  throw new Error('Heartbeat channel has no callable tools')
})

/** Scan inbox for trigger files and deliver them. */
function processInbox() {
  let files: string[]
  try {
    files = readdirSync(INBOX_DIR).filter(f => f.endsWith('.trigger')).sort()
  } catch {
    return
  }

  for (const file of files) {
    const path = join(INBOX_DIR, file)
    try {
      const content = readFileSync(path, 'utf8').trim()
      if (!content) {
        unlinkSync(path)
        continue
      }

      log(`delivering: ${content}`)

      mcp.notification({
        method: 'notifications/claude/channel',
        params: {
          content,
          meta: {
            source: 'heartbeat',
            task: file.replace('.trigger', ''),
            ts: new Date().toISOString(),
          },
        },
      })

      // Remove the trigger file after delivery
      unlinkSync(path)
    } catch (err) {
      log(`error processing ${file}: ${err}`)
    }
  }
}

// Watch the inbox directory for new files
try {
  watch(INBOX_DIR, (eventType, filename) => {
    if (filename && filename.endsWith('.trigger')) {
      // Small delay to ensure the file is fully written
      setTimeout(processInbox, 100)
    }
  })
  log('watching inbox for triggers')
} catch (err) {
  log(`fs.watch failed, falling back to polling: ${err}`)
}

// Also poll every 30 seconds as a fallback (fs.watch can be unreliable)
setInterval(processInbox, 30_000)

// Initial scan on startup
processInbox()

// Connect MCP transport
const transport = new StdioServerTransport()
await mcp.connect(transport)

log('heartbeat channel started')

// Graceful shutdown
function shutdown() {
  log('shutting down')
  setTimeout(() => process.exit(0), 1000)
}
process.stdin.on('end', shutdown)
process.stdin.on('close', shutdown)
process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
