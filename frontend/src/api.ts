export type Kind = 'ble' | 'weather'
export type RangeKey = '24h' | '7d' | '30d' | '1y' | 'all'
/** `humidity` is relative (%), `absolute` the water content of the air (g/m³). */
export type Metric = 'temperature' | 'humidity' | 'absolute'

export interface SensorRef {
  id: string
  name: string
  kind: Kind
  /** Desired room temperature in °C (config), or null. */
  target_temperature: number | null
  /** Temperature factor of the coldest wall spots (indoor sensors only). */
  surface_factor: number | null
}

export interface Latest {
  ts: number
  temperature: number | null
  humidity: number | null
  absolute_humidity: number | null
  dew_point: number | null
  /** Outdoor only: W/m², km/h, mm/h */
  radiation?: number | null
  wind?: number | null
  precipitation?: number | null
}

/** [t_min, t_avg, t_max, h_min, h_avg, h_max, a_min, a_avg, a_max] */
export type Aggregate = [
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
  number | null,
]

export type Level = 'good' | 'warning' | 'critical'

/** Humidity situation of a room right now (computed by the bridge). */
export interface Air {
  absolute_humidity: number | null
  outdoor_absolute_humidity: number | null
  /** Estimated relative humidity at the coldest wall, % (null without outdoor data). */
  surface_humidity: number | null
  level: Level | null
  basis: 'surface' | 'room' | null
  ventilation: 'recommended' | 'not_needed' | 'avoid' | null
  /** Suggested airing time when airing is recommended. */
  minutes: number | null
}

/** How often there was a mould risk in the last 7 days. */
export interface MouldShare {
  /** Limit in %: at the wall (80) or, without outdoor data, in the room (70). */
  threshold: number
  basis: 'surface' | 'room'
  /** 0-1 */
  share: number
  /** hours with samples (at most 168) */
  hours: number
}

export interface Airing {
  sensor_id: string
  start: number
  lowest: number
  /** Temperature drop in K */
  drop: number
  /** Water taken out of the air, g/m³ */
  drying: number
  recovery_minutes: number | null
}

export interface OverviewSensor extends SensorRef {
  latest: Latest | null
  /** Last broadcast battery level and when it came. */
  battery: { ts: number; level: number } | null
  today: Aggregate | null
  /** [ts, temperature, humidity], 30-minute averages of the last 24 hours */
  spark: [number, number | null, number | null][]
  air: Air | null
  mould: MouldShare | null
  airings: { today: number; last: Airing | null } | null
}

export interface Overview {
  generated_at: number
  first_ts: number | null
  sensors: OverviewSensor[]
}

/** [ts, t_min, t_avg, t_max, h_min, h_avg, h_max] */
export type Point = [number, ...Aggregate]

export type GapCause = 'bluetooth' | 'restart' | 'unknown'

export interface SeriesSensor extends SensorRef {
  points: Point[]
  /** Indoor: [ts, humidity at the coldest wall %] per bucket */
  surface?: [number, number | null][]
  /** Outdoor: [ts, radiation W/m², wind km/h, precipitation mm] per bucket */
  weather?: [number, number | null, number | null, number | null][]
}

export interface Series {
  range: RangeKey
  bucket: number | 'day'
  start: number
  end: number
  sensors: SeriesSensor[]
  /** Periods without any indoor reading: [start, end, cause] */
  gaps: [number, number, GapCause][]
  /** Detected airings (ranges up to 30 days) */
  airings: Airing[]
}

export interface Profile {
  days: number
  /** points: [hour, t_avg, h_avg, samples, a_avg] */
  sensors: (SensorRef & { points: [number, number | null, number | null, number, number | null][] })[]
}

export interface Heatmap {
  days: number
  /** cells: [YYYY-MM-DD, hour, t_avg, h_avg, a_avg] */
  sensors: (SensorRef & { cells: [string, number, number | null, number | null, number | null][] })[]
}

export interface RoomDay {
  day: string
  samples: number
  temperature_avg: number | null
  temperature_min: number | null
  temperature_max: number | null
  humidity_avg: number | null
  absolute_avg: number | null
  /** Shares of time below, within and above the target band (null without target). */
  cold: number | null
  on_target: number | null
  warm: number | null
  /** Share of time with mould risk. */
  mould: number | null
  mould_basis: 'surface' | 'room'
  airings: number
  recovery_minutes: number | null
}

export interface OutdoorDay {
  day: string
  samples: number
  temperature_avg: number | null
  temperature_min: number | null
  temperature_max: number | null
  humidity_avg: number | null
  absolute_avg: number | null
  heating_degrees: number | null
  radiation_avg: number | null
  precipitation: number | null
  wind_avg: number | null
}

export interface Daily {
  days: number
  sensors: (SensorRef & { days: (RoomDay | OutdoorDay)[] })[]
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
  /** Host health (null if unknown, e.g. not a Raspberry Pi). */
  system: {
    cpu_temperature: number | null
    undervoltage: boolean | null
    undervoltage_count: number
    last_undervoltage: number | null
  } | null
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
  | 'undervoltage'

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

const OFFSET: Record<Metric, number> = { temperature: 1, humidity: 4, absolute: 7 }

/** Value of a metric from an aggregate: [min, avg, max]. */
export function pick(point: Point, metric: Metric): [number | null, number | null, number | null] {
  const i = OFFSET[metric]
  return [point[i] ?? null, point[i + 1] ?? null, point[i + 2] ?? null]
}
