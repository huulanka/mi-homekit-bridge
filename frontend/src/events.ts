// Texts, severities and grouping of bridge events (unit-tested in events.test.ts).
import type { Severity } from './advice'
import type { BridgeEvent } from './api'
import { t, type MessageKey } from './i18n'

const SEVERITY: Record<string, Severity | undefined> = {
  sensor_lost: 'warning',
  scan_silent: 'warning',
  scan_failed: 'warning',
  passive_unavailable: 'warning',
  undervoltage: 'warning',
  bluetooth_reset: 'critical',
  bluetooth_failed: 'critical',
  sensor_back: 'good',
  scan_recovered: 'good',
}

const KNOWN = new Set([
  'started',
  'stopped',
  'restart',
  'update',
  'sensor_lost',
  'sensor_back',
  'scan_silent',
  'scan_failed',
  'scan_recovered',
  'bluetooth_reset',
  'bluetooth_failed',
  'passive_unavailable',
  'undervoltage',
])

export function describeEvent(event: BridgeEvent, names: Record<string, string>): string {
  if (!KNOWN.has(event.kind)) return t('event_unknown', { kind: event.kind })
  const sensor = event.sensor_id ? (names[event.sensor_id] ?? event.sensor_id) : ''
  if (event.kind === 'restart' && Number(event.data.count) > 1) return t('event_restart_many', event.data)
  return t(`event_${event.kind}` as MessageKey, { ...event.data, sensor })
}

export function eventSeverity(kind: string): Severity | undefined {
  return SEVERITY[kind]
}

/** A stop followed by a start within this time is a restart. */
const RESTART_SECONDS = 120
/** Restarts this close to each other (e.g. several deploys) become one entry. */
const MERGE_SECONDS = 30 * 60

/** Turn stop + start pairs into restarts, a new version into an update, and
 * several restarts in a row into one entry with a count. Input and output are
 * newest first; the input is not modified. */
export function groupEvents(events: BridgeEvent[]): BridgeEvent[] {
  const result: BridgeEvent[] = []
  let version: string | undefined
  for (const event of [...events].reverse()) {
    if (event.kind !== 'started') {
      result.push(event)
      continue
    }
    const running = event.data.version === undefined ? undefined : String(event.data.version)
    const stop = result.findLastIndex((e) => e.kind === 'stopped' && event.ts - e.ts <= RESTART_SECONDS)
    if (stop >= 0) result.splice(stop, 1)
    const previous = version
    if (running) version = running

    if (previous && running && running !== previous) {
      result.push({ ts: event.ts, kind: 'update', sensor_id: null, data: { version: running, previous } })
      continue
    }
    if (stop < 0) {
      result.push(event)
      continue
    }
    const last = result[result.length - 1]
    if (last?.kind === 'restart' && event.ts - last.ts <= MERGE_SECONDS) {
      result[result.length - 1] = { ...last, ts: event.ts, data: { ...last.data, count: Number(last.data.count) + 1 } }
      continue
    }
    result.push({ ts: event.ts, kind: 'restart', sensor_id: null, data: { version: running ?? '', count: 1 } })
  }
  return result.reverse()
}
