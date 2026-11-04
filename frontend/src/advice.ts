// Pure rules behind the room-card hints (unit-tested in advice.test.ts).
import type { HumidShare, OverviewSensor, Status } from './api'

/** Within this many kelvin of the target counts as "on target". */
export const TARGET_TOLERANCE = 0.5

/** Rule of thumb for radiator thermostat dials (numbers 1-5): 1 is about 12 °C and
 * every number adds about 4 °C, so 3 is about 20 °C. Real heads vary by ±1-2 °C. */
const DIAL_ONE = 12
const KELVIN_PER_STEP = 4
const DIAL_MIN = 1
const DIAL_MAX = 5

/** Above this outdoor temperature the heating is usually off ("Heizgrenze"), so
 * turning the thermostat would not change anything. */
export const HEATING_LIMIT = 15

/** Minimum number of 30-minute buckets for a meaningful 24-hour average. */
const MIN_BUCKETS = 6

export interface TargetAdvice {
  target: number
  /** Current value minus target (K). */
  now: number | null
  /** 24-hour average minus target (K); the basis of the advice. */
  average: number | null
  status: 'ok' | 'warm' | 'cold' | 'unknown'
  /** Suggested change on the dial in steps, rounded to quarter steps: negative = turn
   * down. Null when no change is advised (on target, no data or heating season over). */
  steps: number | null
  /** Dial setting for the target by the rule of thumb, in half steps. */
  dial: number
}

export function dialFor(target: number): number {
  const raw = DIAL_MIN + (target - DIAL_ONE) / KELVIN_PER_STEP
  return Math.min(DIAL_MAX, Math.max(DIAL_MIN, Math.round(raw * 2) / 2))
}

export function average(values: (number | null)[]): number | null {
  const numbers = values.filter((v): v is number => v !== null)
  if (numbers.length < MIN_BUCKETS) return null
  return numbers.reduce((a, b) => a + b, 0) / numbers.length
}

export function targetAdvice(
  sensor: OverviewSensor,
  outdoor: OverviewSensor | undefined,
  now: number,
): TargetAdvice | null {
  const target = sensor.target_temperature
  if (target === null || sensor.kind !== 'ble') return null
  const current = sensor.latest?.temperature ?? null
  const mean = average(sensor.spark.map((s) => s[1]))
  const basis = mean ?? current
  const offset = current === null ? null : round1(current - target)
  const avg = mean === null ? null : round1(mean - target)
  const dial = dialFor(target)
  if (basis === null) return { target, now: offset, average: avg, status: 'unknown', steps: null, dial }

  const deviation = basis - target
  const status = Math.abs(deviation) <= TARGET_TOLERANCE ? 'ok' : deviation > 0 ? 'warm' : 'cold'
  const outside = freshOutdoorTemperature(outdoor, now)
  const heating = outside === null || outside < HEATING_LIMIT
  let steps: number | null = null
  if (status !== 'ok' && heating && mean !== null) {
    const quarter = Math.max(1, Math.round((Math.abs(deviation) / KELVIN_PER_STEP) * 4))
    steps = (deviation > 0 ? -quarter : quarter) / 4
  }
  return { target, now: offset, average: avg, status, steps, dial }
}

export type Severity = 'good' | 'warning' | 'critical'

/** Share of time above 60 % relative humidity: rarely is fine, more than half the
 * time means the room stays damp (mould risk). */
export function humidSeverity(humid: HumidShare): Severity {
  if (humid.share <= 0.1) return 'good'
  if (humid.share <= 0.5) return 'warning'
  return 'critical'
}

/** Signal strength in bars (1-4). Below about -90 dBm reception gets unreliable. */
export function signalBars(rssi: number): 1 | 2 | 3 | 4 {
  if (rssi >= -70) return 4
  if (rssi >= -80) return 3
  if (rssi >= -88) return 2
  return 1
}

/** Outdoor values are fetched every 15 minutes; older than this counts as stale. */
export const OUTDOOR_FRESH_SECONDS = 75 * 60

export function freshOutdoorTemperature(outdoor: OverviewSensor | undefined, now: number): number | null {
  const latest = outdoor?.latest
  if (!latest || latest.temperature === null || now - latest.ts > OUTDOOR_FRESH_SECONDS) return null
  return latest.temperature
}

export interface Banner {
  kind: 'offline' | 'bluetooth' | 'homekit'
  severity: 'warning' | 'critical'
  since: number | null
}

/** Banners for the top of the page, most severe first. */
export function banners(status: Status | undefined, offlineSince: number | null): Banner[] {
  const result: Banner[] = []
  if (offlineSince !== null) result.push({ kind: 'offline', severity: 'critical', since: offlineSince })
  if (status && offlineSince === null) {
    const state = status.bluetooth.state
    if (state === 'failed' || state === 'recovering') {
      result.push({ kind: 'bluetooth', severity: state === 'failed' ? 'critical' : 'warning', since: status.bluetooth.since })
    }
    if (!status.homekit.paired) result.push({ kind: 'homekit', severity: 'warning', since: null })
  }
  return result
}

function round1(value: number): number {
  return Math.round(value * 10) / 10
}
