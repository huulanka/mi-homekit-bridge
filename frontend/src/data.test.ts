import { describe, expect, it } from 'vitest'
import type { Point, Series } from './api'
import { computeDeltas, heatmapCells, profileValues, withGaps } from './data'

const point = (ts: number, temperature: number | null, humidity: number | null = null): Point => [
  ts,
  temperature,
  temperature,
  temperature,
  humidity,
  humidity,
  humidity,
]

describe('withGaps', () => {
  it('breaks lines where samples are missing', () => {
    expect(withGaps([[0, 1], [300, 2], [1500, 3]], 300)).toEqual([[0, 1], [300, 2], [600, null], [1500, 3]])
  })
  it('keeps continuous data untouched', () => {
    expect(withGaps([[0, 1], [300, 2]], 300)).toEqual([[0, 1], [300, 2]])
  })
})

describe('computeDeltas', () => {
  const series: Series = {
    range: '24h',
    bucket: 300,
    start: 0,
    end: 3600,
    sensors: [
      { id: 'a', name: 'Living', kind: 'ble', points: [point(0, 21), point(300, 21.5), point(4000, 22)] },
      { id: 'w', name: 'Outdoor', kind: 'weather', points: [point(0, 5), point(900, 6)] },
    ],
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

  it('is empty without an outdoor sensor', () => {
    expect(computeDeltas({ ...series, sensors: series.sensors.slice(0, 1) }, 'temperature')).toEqual([])
  })
})

describe('profileValues', () => {
  it('returns 24 hours with gaps as null', () => {
    const values = profileValues([[7, 20, 50, 3], [8, 21, 48, 3]], 'humidity')
    expect(values).toHaveLength(24)
    expect(values[7]).toBe(50)
    expect(values[0]).toBeNull()
  })
})

describe('heatmapCells', () => {
  it('indexes days and computes the value range', () => {
    const result = heatmapCells(
      {
        id: 'a',
        name: 'Living',
        kind: 'ble',
        cells: [
          ['2026-11-02', 7, 19, 50],
          ['2026-11-01', 7, 18, 52],
          ['2026-11-01', 8, null, 51],
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
