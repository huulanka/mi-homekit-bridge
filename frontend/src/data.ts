// Pure data transformations for the charts (unit-tested in data.test.ts).
import { pick, type Heatmap, type Metric, type Profile, type Series } from './api'

export const HOURS = Array.from({ length: 24 }, (_, hour) => hour)

export function stepMs(bucket: number | 'day'): number {
  return (bucket === 'day' ? 86400 : bucket) * 1000
}

/** Insert null points where data is missing, so lines break instead of bridging gaps. */
export function withGaps(points: [number, number | null][], step: number): [number, number | null][] {
  const result: [number, number | null][] = []
  let previous: number | undefined
  for (const point of points) {
    if (previous !== undefined && point[0] - previous > step * 1.5) {
      result.push([previous + step, null])
    }
    result.push(point)
    previous = point[0]
  }
  return result
}

export interface DeltaSeries {
  id: string
  name: string
  points: [number, number | null][]
}

/** Indoor minus outdoor per indoor sensor (timestamps in ms). Outdoor values, often
 * sampled less frequently, are carried forward for up to one bucket or 30 minutes. */
export function computeDeltas(data: Series, metric: Metric): DeltaSeries[] {
  const outdoor = data.sensors.find((s) => s.kind === 'weather')
  if (!outdoor) return []
  const tolerance = Math.max(stepMs(data.bucket), 30 * 60 * 1000)
  const outside = outdoor.points
    .map((p) => [p[0] * 1000, pick(p, metric)[1]] as const)
    .filter((p): p is readonly [number, number] => p[1] !== null)

  return data.sensors
    .filter((s) => s.kind !== 'weather')
    .map((sensor) => {
      let j = 0
      const points = sensor.points.map((p): [number, number | null] => {
        const ts = p[0] * 1000
        const inside = pick(p, metric)[1]
        while (j + 1 < outside.length && outside[j + 1]![0] <= ts) j++
        const reference = outside[j]
        if (inside === null || !reference || reference[0] > ts || ts - reference[0] > tolerance) {
          return [ts, null]
        }
        return [ts, Math.round((inside - reference[1]) * 100) / 100]
      })
      return { id: sensor.id, name: sensor.name, points }
    })
}

/** 24 values per sensor (null for hours without samples). */
export function profileValues(points: Profile['sensors'][number]['points'], metric: Metric): (number | null)[] {
  const byHour = new Map(points.map(([hour, temperature, humidity]) => [hour, metric === 'temperature' ? temperature : humidity]))
  return HOURS.map((hour) => byHour.get(hour) ?? null)
}

/** Heatmap cells as [day index, hour, value] plus the day labels and value range. */
export function heatmapCells(sensor: Heatmap['sensors'][number], metric: Metric) {
  const days = [...new Set(sensor.cells.map((c) => c[0]))].sort()
  const index = new Map(days.map((day, i) => [day, i]))
  const cells = sensor.cells
    .map(([day, hour, temperature, humidity]) => [index.get(day)!, hour, metric === 'temperature' ? temperature : humidity] as const)
    .filter((c): c is readonly [number, number, number] => c[2] !== null)
  const values = cells.map((c) => c[2])
  return { days, cells, min: values.length ? Math.min(...values) : 0, max: values.length ? Math.max(...values) : 1 }
}
