#!/usr/bin/env bun
/**
 * Heartbeat channel for Claude Code.
 *
 * Minimal file-watching MCP channel that delivers trigger messages
 * to a running Claude Code session. External processes (launchd, cron)
 * write trigger files to the inbox directory; this server picks them
 * up and emits channel notifications.
 *
 * Also runs an HTTP webhook endpoint (Bun.serve) for programmatic
 * triggers from external services (GitHub stars, iOS shortcuts, etc.).
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
import { createHmac, timingSafeEqual } from 'crypto'

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

// ---------------------------------------------------------------------------
// Webhook HTTP server
// ---------------------------------------------------------------------------

interface WebhookAction {
  template: string
  allowed_fields: string[]
}

interface WebhooksConfig {
  port?: number
  actions: Record<string, WebhookAction>
}

/** Load .env file and set missing env vars */
function loadDotenv(path: string) {
  try {
    const content = readFileSync(path, 'utf8')
    for (const line of content.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith('#')) continue
      const eq = trimmed.indexOf('=')
      if (eq === -1) continue
      const key = trimmed.slice(0, eq).trim()
      const val = trimmed.slice(eq + 1).trim()
      if (!process.env[key]) process.env[key] = val
    }
  } catch {}
}

loadDotenv(join(STATE_DIR, '.env'))

/** Load webhooks config from JSON file */
function loadWebhooksConfig(): WebhooksConfig | null {
  const configPath = join(STATE_DIR, 'webhooks.json')
  try {
    return JSON.parse(readFileSync(configPath, 'utf8')) as WebhooksConfig
  } catch {
    return null
  }
}

/** Sanitize a single field value */
function sanitizeField(value: string): string {
  return value
    .replace(/[\n\r]/g, ' ')
    .replace(/<\/?channel[^>]*>/gi, '')
    .replace(/\[HEARTBEAT:[^\]]*\]/g, '')
    .replace(/```/g, '')
    .slice(0, 200)
}

/** Validate HMAC signature (timing-safe) */
function validateSignature(secret: string, signature: string, timestamp: string, action: string, data: Record<string, string>): boolean {
  const payload = `${timestamp}.${action}.${JSON.stringify(data)}`
  const expected = 'sha256=' + createHmac('sha256', secret).update(payload).digest('hex')
  if (signature.length !== expected.length) return false
  try {
    return timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
  } catch {
    return false
  }
}

// Rate limiting state
const rateLimitPerAction = new Map<string, number>()  // action -> last request timestamp
const globalRequestTimes: number[] = []
const RATE_PER_ACTION_MS = 10_000  // 1 per 10 seconds per action
const RATE_GLOBAL_WINDOW_MS = 60_000  // 60 second window
const RATE_GLOBAL_MAX = 30  // 30 per minute

function checkRateLimit(action: string): boolean {
  const now = Date.now()

  // Per-action check
  const lastAction = rateLimitPerAction.get(action) ?? 0
  if (now - lastAction < RATE_PER_ACTION_MS) return false

  // Global check — prune old entries
  while (globalRequestTimes.length > 0 && now - globalRequestTimes[0] > RATE_GLOBAL_WINDOW_MS) {
    globalRequestTimes.shift()
  }
  if (globalRequestTimes.length >= RATE_GLOBAL_MAX) return false

  // Record
  rateLimitPerAction.set(action, now)
  globalRequestTimes.push(now)
  return true
}

/** Write a .trigger file to the inbox */
function writeTriggerFile(content: string, label: string) {
  const ts = Date.now()
  const filename = `${ts}-webhook-${label}.trigger`
  writeFileSync(join(INBOX_DIR, filename), content)
}

const CORS_HEADERS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Heartbeat-Signature, X-Heartbeat-Timestamp',
}

const startTime = Date.now()

function startWebhookServer() {
  const config = loadWebhooksConfig()
  const secret = process.env.HEARTBEAT_WEBHOOK_SECRET
  const port = Number(process.env.HEARTBEAT_PORT) || config?.port || 7600

  if (!secret) {
    log('webhook: no HEARTBEAT_WEBHOOK_SECRET set — /trigger endpoint disabled')
  }
  if (!config) {
    log('webhook: no webhooks.json found — /trigger endpoint disabled')
  }

  Bun.serve({
    port,
    fetch: async (req) => {
      const url = new URL(req.url)
      const remoteAddr = req.headers.get('x-forwarded-for') ?? 'unknown'

      // CORS preflight
      if (req.method === 'OPTIONS') {
        return new Response(null, { status: 204, headers: CORS_HEADERS })
      }

      // GET /health — no auth required
      if (url.pathname === '/health' && req.method === 'GET') {
        const uptime = Math.floor((Date.now() - startTime) / 1000)
        return Response.json({ status: 'ok', uptime }, { headers: CORS_HEADERS })
      }

      // POST /trigger
      if (url.pathname === '/trigger' && req.method === 'POST') {
        if (!secret || !config) {
          return Response.json(
            { error: 'webhook endpoint not configured' },
            { status: 503, headers: CORS_HEADERS },
          )
        }

        // Validate headers
        const signature = req.headers.get('x-heartbeat-signature')
        const timestamp = req.headers.get('x-heartbeat-timestamp')
        if (!signature || !timestamp) {
          log(`webhook: missing auth headers from ${remoteAddr}`)
          return Response.json(
            { error: 'missing signature or timestamp header' },
            { status: 401, headers: CORS_HEADERS },
          )
        }

        // Timestamp freshness (5 min window)
        const tsAge = Math.abs(Date.now() / 1000 - Number(timestamp))
        if (isNaN(tsAge) || tsAge > 300) {
          log(`webhook: stale timestamp from ${remoteAddr}`)
          return Response.json(
            { error: 'timestamp too old or invalid' },
            { status: 401, headers: CORS_HEADERS },
          )
        }

        // Parse body
        let body: { action?: string; data?: Record<string, string> }
        try {
          body = await req.json()
        } catch {
          return Response.json(
            { error: 'invalid JSON body' },
            { status: 400, headers: CORS_HEADERS },
          )
        }

        const action = body.action
        const data = body.data ?? {}

        if (!action || typeof action !== 'string') {
          return Response.json(
            { error: 'missing action field' },
            { status: 400, headers: CORS_HEADERS },
          )
        }

        // Validate HMAC
        if (!validateSignature(secret, signature, timestamp, action, data)) {
          log(`webhook: invalid signature from ${remoteAddr}`)
          return Response.json(
            { error: 'invalid signature' },
            { status: 403, headers: CORS_HEADERS },
          )
        }

        // Look up action in registry
        const actionDef = config.actions[action]
        if (!actionDef) {
          return Response.json(
            { error: `unknown action: ${action}` },
            { status: 400, headers: CORS_HEADERS },
          )
        }

        // Rate limit
        if (!checkRateLimit(action)) {
          log(`webhook: rate limited action=${action}`)
          return Response.json(
            { error: 'rate limited' },
            { status: 429, headers: CORS_HEADERS },
          )
        }

        // Sanitize data fields (only allowed fields)
        const sanitized: Record<string, string> = {}
        for (const field of actionDef.allowed_fields) {
          if (typeof data[field] === 'string') {
            sanitized[field] = sanitizeField(data[field])
          }
        }

        // Build trigger message from template
        let message = actionDef.template
        for (const [key, val] of Object.entries(sanitized)) {
          message = message.replaceAll(`{${key}}`, val)
        }
        // Remove any unreplaced placeholders
        message = message.replace(/\{[a-zA-Z_]+\}/g, '')

        // Write trigger file
        writeTriggerFile(message, action)
        log(`webhook: POST /trigger action=${action} (200)`)

        return Response.json(
          { status: 'ok', action, message },
          { status: 200, headers: CORS_HEADERS },
        )
      }

      // 404 for everything else
      return Response.json(
        { error: 'not found' },
        { status: 404, headers: CORS_HEADERS },
      )
    },
  })

  log(`webhook: HTTP server listening on port ${port}`)
}

// Start webhook server (non-blocking, won't crash if port is taken)
try {
  startWebhookServer()
} catch (err) {
  log(`webhook: failed to start HTTP server: ${err}`)
}

// ---------------------------------------------------------------------------
// MCP Channel Server
// ---------------------------------------------------------------------------

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
