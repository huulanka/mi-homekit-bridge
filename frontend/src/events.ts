// Texts and severities of bridge events (unit-tested in events.test.ts).
import type { Severity } from './advice'
import type { BridgeEvent } from './api'
import { t, type MessageKey } from './i18n'

const SEVERITY: Record<string, Severity | undefined> = {
  sensor_lost: 'warning',
  scan_silent: 'warning',
  scan_failed: 'warning',
  bluetooth_reset: 'critical',
  bluetooth_failed: 'critical',
  sensor_back: 'good',
  scan_recovered: 'good',
}

const KNOWN = new Set([
  'started',
  'stopped',
  'sensor_lost',
  'sensor_back',
  'scan_silent',
  'scan_failed',
  'scan_recovered',
  'bluetooth_reset',
  'bluetooth_failed',
])

export function describeEvent(event: BridgeEvent, names: Record<string, string>): string {
  if (!KNOWN.has(event.kind)) return t('event_unknown', { kind: event.kind })
  const sensor = event.sensor_id ? (names[event.sensor_id] ?? event.sensor_id) : ''
  return t(`event_${event.kind}` as MessageKey, { ...event.data, sensor })
}

export function eventSeverity(kind: string): Severity | undefined {
  return SEVERITY[kind]
}
