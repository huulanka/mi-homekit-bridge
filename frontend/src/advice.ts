// Pure rules behind the room-card hints (unit-tested in advice.test.ts).
import type { HumidShare, OverviewSensor, Status } from './api'

/** Within this many kelvin of the target counts as "on target". */
export const TARGET_TOLERANCE = 0.5

/** Above this outdoor temperature the heating is usually off ("Heizgrenze"), so
 * turning the thermostat would not change anything. */
export const HEATING_LIMIT = 15

/** The advice is based on the median of the last 3 hours (six 30-minute buckets):
 * airing for a few minutes barely moves it, and a turned thermostat shows within
 * hours (a 24-hour average would keep asking for more for a whole day). */
const RECENT_BUCKETS = 6
const MIN_RECENT = 4

/** Rule of thumb for radiator thermostat dials: each mark between the numbers is
 * about 1 °C. Dials differ, so the advice stays relative: no absolute setting. */
const KELVIN_PER_MARK = 1

export interface TargetAdvice {
  target: number
  /** Recent temperature minus target (K), or null without data. */
  deviation: number | null
  status: 'ok' | 'warm' | 'cold' | 'unknown'
  /** Marks to turn the dial, negative = down. Null when no change is advised
   * (on target, too little data, or outside the heating season). */
  marks: number | null
  /** Too warm, but it is warm outside: the heating is probably off anyway. */
  heatingOff: boolean
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
}

/** Median temperature of the last 3 hours, or null with too few buckets. */
export function recentTemperature(spark: OverviewSensor['spark']): number | null {
  const values = spark
    .slice(-RECENT_BUCKETS)
    .map((s) => s[1])
    .filter((v): v is number => v !== null)
  return values.length >= MIN_RECENT ? median(values) : null
}

export function targetAdvice(
  sensor: OverviewSensor,
  outdoor: OverviewSensor | undefined,
  now: number,
): TargetAdvice | null {
  const target = sensor.target_temperature
  if (target === null || sensor.kind !== 'ble') return null
  const recent = recentTemperature(sensor.spark)
  const basis = recent ?? sensor.latest?.temperature ?? null
  if (basis === null) return { target, deviation: null, status: 'unknown', marks: null, heatingOff: false }

  const deviation = Math.round((basis - target) * 10) / 10
  const status = Math.abs(deviation) <= TARGET_TOLERANCE ? 'ok' : deviation > 0 ? 'warm' : 'cold'
  const outside = freshOutdoorTemperature(outdoor, now)
  const heatingOff = status === 'warm' && outside !== null && outside >= HEATING_LIMIT
  let marks: number | null = null
  if (status !== 'ok' && !heatingOff && recent !== null) {
    const count = Math.max(1, Math.round(Math.abs(deviation) / KELVIN_PER_MARK))
    marks = deviation > 0 ? -count : count
  }
  return { target, deviation, status, marks, heatingOff }
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
