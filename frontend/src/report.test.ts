import { describe, expect, it } from 'vitest'
import type { Daily, OutdoorDay, RoomDay } from './api'
import { degreeDayPeriods, roomWeek, shiftDay, targetPeriods, weeklyReport } from './report'

function room(day: string, overrides: Partial<RoomDay> = {}): RoomDay {
  return {
    day,
    samples: 288,
    temperature_avg: 21,
    temperature_min: 20,
    temperature_max: 22,
    humidity_avg: 55,
    absolute_avg: 10,
    cold: 0.1,
    on_target: 0.8,
    warm: 0.1,
    mould: 0,
    mould_basis: 'surface',
    airings: 1,
    recovery_minutes: 40,
    ...overrides,
  }
}

function outside(day: string, mean: number): OutdoorDay {
  return {
    day,
    samples: 96,
    temperature_avg: mean,
    temperature_min: mean - 3,
    temperature_max: mean + 3,
    humidity_avg: 80,
    absolute_avg: 5,
    heating_degrees: mean < 15 ? 20 - mean : 0,
    radiation_avg: 80,
    precipitation: 1,
    wind_avg: 10,
  }
}

const days = (from: string, count: number) => Array.from({ length: count }, (_, i) => shiftDay(from, i))

describe('shiftDay', () => {
  it('moves across month ends and daylight saving', () => {
    expect(shiftDay('2026-11-01', -1)).toBe('2026-10-31')
    expect(shiftDay('2026-10-24', 2)).toBe('2026-10-26')
  })
})

describe('roomWeek', () => {
  it('weights by samples and sums mould hours', () => {
    const week = roomWeek([room('2026-11-01', { temperature_avg: 20, samples: 100, mould: 0.25 }), room('2026-11-02', { temperature_avg: 23, samples: 200 })])
    expect(week.temperature).toBe(22)
    expect(week.mouldHours).toBe(6)
    expect(week.airingsPerDay).toBe(1)
    expect(week.recoveryMinutes).toBe(40)
  })
})

describe('weeklyReport', () => {
  const daily: Daily = {
    days: 15,
    sensors: [
      {
        id: 'L',
        name: 'Living',
        kind: 'ble',
        target_temperature: 21,
        surface_factor: 0.8,
        days: [
          ...days('2026-10-21', 7).map((d) => room(d, { temperature_avg: 22 })),
          ...days('2026-10-28', 8).map((d) => room(d, { temperature_avg: 21 })),
        ],
      },
      { id: 'w', name: 'Outdoor', kind: 'weather', target_temperature: null, surface_factor: null, days: days('2026-10-28', 8).map((d) => outside(d, 5)) },
    ],
  }

  it('reports the 7 complete days before today against the week before', () => {
    const report = weeklyReport(daily, '2026-11-04')!
    expect([report.start, report.end]).toEqual(['2026-10-28', '2026-11-03'])
    const [living] = report.rooms
    expect(living?.current.days).toBe(7) // today does not count
    expect(living?.current.temperature).toBe(21)
    expect(living?.previous?.temperature).toBe(22)
    expect(report.outdoor?.current.heatingDegrees).toBe(105)
    expect(report.outdoor?.previous).toBeNull() // no outdoor data the week before
  })

  it('is null without complete days', () => {
    expect(weeklyReport(daily, '2026-10-20')).toBeNull()
  })
})

describe('periods', () => {
  it('aggregates the time in target per month', () => {
    const periods = targetPeriods(
      [room('2026-10-30', { cold: 0, on_target: 1, warm: 0 }), room('2026-10-31', { cold: 0, on_target: 0.5, warm: 0.5 }), room('2026-11-01', { on_target: null })],
      'month',
    )
    expect(periods).toEqual([{ key: '2026-10', cold: 0, onTarget: 0.75, warm: 0.25 }])
  })

  it('sums heating degree days per month', () => {
    const periods = degreeDayPeriods([outside('2026-10-30', 5), outside('2026-10-31', 10), outside('2026-11-01', 16)], 'month')
    expect(periods).toEqual([
      { key: '2026-10', degrees: 25, temperature: 7.5 },
      { key: '2026-11', degrees: 0, temperature: 16 },
    ])
  })
})
