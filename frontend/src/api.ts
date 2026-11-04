export type Kind = 'ble' | 'weather'
export type RangeKey = '24h' | '7d' | '30d' | '1y' | 'all'
export type Metric = 'temperature' | 'humidity'

export interface SensorRef {
  id: string
  name: string
  kind: Kind
  /** Desired room temperature in °C (config), or null. */
  target_temperature: number | null
}

export interface Latest {
  ts: number
  temperature: number | null
  humidity: number | null
  battery: number | null
  dew_point: number | null
}

/** [t_min, t_avg, t_max, h_min, h_avg, h_max] */
export type Aggregate = [number | null, number | null, number | null, number | null, number | null, number | null]

/** How often the humidity was above `threshold` % in the last 7 days. */
export interface HumidShare {
  threshold: number
  /** 0-1 */
  share: number
  /** hours with samples (at most 168) */
  hours: number
}

export interface OverviewSensor extends SensorRef {
  latest: Latest | null
  today: Aggregate | null
  /** [ts, temperature, humidity], 30-minute averages of the last 24 hours */
  spark: [number, number | null, number | null][]
  humid: HumidShare | null
}

export interface Overview {
  generated_at: number
  first_ts: number | null
  sensors: OverviewSensor[]
}

/** [ts, t_min, t_avg, t_max, h_min, h_avg, h_max] */
export type Point = [number, ...Aggregate]

export interface Series {
  range: RangeKey
  bucket: number | 'day'
  start: number
  end: number
  sensors: (SensorRef & { points: Point[] })[]
}

export interface Profile {
  days: number
  /** points: [hour, t_avg, h_avg, samples] */
  sensors: (SensorRef & { points: [number, number | null, number | null, number][] })[]
}

export interface Heatmap {
  days: number
  /** cells: [YYYY-MM-DD, hour, t_avg, h_avg] */
  sensors: (SensorRef & { cells: [string, number, number | null, number | null][] })[]
}

export type BluetoothState = 'starting' | 'running' | 'recovering' | 'failed'

export interface SensorLive {
  id: string
  name: string
  reporting: boolean
  problem: boolean
  last_seen: number | null
  rssi: number | null
}

/** Live state of the bridge (absent in demo mode). */
export interface Status {
  version: string
  started_at: number
  bluetooth: {
    state: BluetoothState
    since: number
    error: string | null
    scanning_mode: 'active' | 'passive'
    last_advertisement: number | null
  }
  homekit: { paired: boolean; controllers: number }
  sensors: SensorLive[]
  problems: string[]
}

export type EventKind =
  | 'started'
  | 'stopped'
  | 'sensor_lost'
  | 'sensor_back'
  | 'scan_silent'
  | 'scan_failed'
  | 'scan_recovered'
  | 'bluetooth_reset'
  | 'bluetooth_failed'
  | 'passive_unavailable'

export interface BridgeEvent {
  ts: number
  kind: EventKind | string
  sensor_id: string | null
  data: Record<string, string | number>
}

export interface Events {
  events: BridgeEvent[]
}

export async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
  return (await response.json()) as T
}

/** Value of a metric from an aggregate: [min, avg, max]. */
export function pick(point: Point, metric: Metric): [number | null, number | null, number | null] {
  return metric === 'temperature' ? [point[1], point[2], point[3]] : [point[4], point[5], point[6]]
}
