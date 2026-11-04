import { describe, expect, it } from 'vitest'
import type { Point, Series } from './api'
import { computeDeltas, heatmapCells, lineStep, profileValues, withGaps } from './data'

const point = (ts: number, temperature: number | null, humidity: number | null = null, absolute: number | null = null): Point => [
  ts,
  temperature,
  temperature,
  temperature,
  humidity,
  humidity,
  humidity,
  absolute,
  absolute,
  absolute,
]

describe('withGaps', () => {
  it('breaks lines where samples are missing', () => {
    expect(withGaps([[0, 1], [300, 2], [1500, 3]], 300)).toEqual([[0, 1], [300, 2], [600, null], [1500, 3]])
  })
  it('keeps continuous data untouched', () => {
    expect(withGaps([[0, 1], [300, 2]], 300)).toEqual([[0, 1], [300, 2]])
  })
})

describe('lineStep', () => {
  it('uses the spacing of sensors sampled less often than the buckets', () => {
    expect(lineStep([0, 900, 1800, 2700, 4500], 300)).toBe(900) // outdoor every 15 min in the 5-min view
    expect(lineStep([0, 300, 600, 900], 300)).toBe(300)
    expect(lineStep([0, 900], 300)).toBe(300)
  })
})

describe('computeDeltas', () => {
  const series: Series = {
    range: '24h',
    bucket: 300,
    start: 0,
    end: 3600,
    sensors: [
      {
        id: 'a',
        name: 'Living',
        kind: 'ble',
        target_temperature: null,
        surface_factor: 0.7,
        points: [point(0, 21, 50, 9.2), point(300, 21.5), point(4000, 22)],
      },
      { id: 'w', name: 'Outdoor', kind: 'weather', target_temperature: null, surface_factor: null, points: [point(0, 5, 80, 5.4), point(900, 6)] },
    ],
    gaps: [],
    airings: [],
  }

  it('subtracts the latest outdoor value and carries it forward up to 30 minutes', () => {
    const [living] = computeDeltas(series, 'temperature')
    expect(living?.name).toBe('Living')
    expect(living?.points).toEqual([
      [0, 16],
      [300_000, 16.5],
      [4_000_000, null], // outdoor value is older than 30 minutes
    ])
  })

  it('compares the water content, not the relative humidity', () => {
    const [living] = computeDeltas(series, 'absolute')
    expect(living?.points[0]).toEqual([0, 3.8])
  })

  it('is empty without an outdoor sensor', () => {
    expect(computeDeltas({ ...series, sensors: series.sensors.slice(0, 1) }, 'temperature')).toEqual([])
  })
})

describe('profileValues', () => {
  it('returns 24 hours with gaps as null', () => {
    const values = profileValues([[7, 20, 50, 3, 8.6], [8, 21, 48, 3, 8.8]], 'humidity')
    expect(values).toHaveLength(24)
    expect(values[7]).toBe(50)
    expect(values[0]).toBeNull()
    expect(profileValues([[7, 20, 50, 3, 8.6]], 'absolute')[7]).toBe(8.6)
  })
})

describe('heatmapCells', () => {
  it('indexes days and computes the value range', () => {
    const result = heatmapCells(
      {
        id: 'a',
        name: 'Living',
        kind: 'ble',
        target_temperature: null,
        surface_factor: 0.7,
        cells: [
          ['2026-11-02', 7, 19, 50, 8.2],
          ['2026-11-01', 7, 18, 52, 8.0],
          ['2026-11-01', 8, null, 51, null],
        ],
      },
      'temperature',
    )
    expect(result.days).toEqual(['2026-11-01', '2026-11-02'])
    expect(result.cells).toEqual([
      [1, 7, 19],
      [0, 7, 18],
    ])
    expect([result.min, result.max]).toEqual([18, 19])
  })
})
