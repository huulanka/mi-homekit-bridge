import { describe, expect, it } from 'vitest'
import type { OverviewSensor, Status } from './api'
import { banners, median, mouldSeverity, mouldWeekSeverity, recentTemperature, signalBars, targetAdvice } from './advice'

const NOW = 1_800_000_000

function room(temps: (number | null)[], latest: number | null, target: number | null = 18): OverviewSensor {
  return {
    id: 'A',
    name: 'Bedroom',
    kind: 'ble',
    target_temperature: target,
    surface_factor: 0.7,
    latest: { ts: NOW, temperature: latest, humidity: 60, absolute_humidity: null, dew_point: null },
    battery: null,
    today: null,
    spark: temps.map((t, i) => [NOW - (temps.length - i) * 1800, t, null]),
    air: null,
    mould: null,
    airings: null,
  }
}

function outdoor(temperature: number, age = 600): OverviewSensor {
  return { ...room([], temperature, null), id: 'weather', kind: 'weather', latest: { ts: NOW - age, temperature, humidity: 80, absolute_humidity: null, dew_point: null } }
}

const day = (t: number) => Array<number>(48).fill(t)

describe('recentTemperature', () => {
  it('takes the median of the last 3 hours', () => {
    const spark = [20, 20, 20, 24, 24, 24, 23, 24, 15, 24].map((t, i) => [i, t, null] as [number, number, null])
    expect(recentTemperature(spark)).toBe(24) // the 15 (airing) does not count
  })
  it('needs at least 2 hours of data', () => {
    expect(recentTemperature([[0, 20, null], [1, null, null], [2, 21, null]])).toBeNull()
  })
  it('handles even counts', () => {
    expect(median([1, 2, 3, 4])).toBe(2.5)
  })
})

describe('targetAdvice', () => {
  it('is on target within half a kelvin', () => {
    const advice = targetAdvice(room(day(18.4), 18.2), outdoor(5), NOW)!
    expect(advice.status).toBe('ok')
    expect(advice.marks).toBeNull()
  })

  it('advises turning down in marks: the living room at dial 3 with 24 °C', () => {
    const advice = targetAdvice(room(day(24), 24, 21), outdoor(5), NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.deviation).toBe(3)
    expect(advice.marks).toBe(-3)
  })

  it('follows a turned thermostat within hours, not a day', () => {
    // 24 °C all day, but the last 3 hours (after turning down) at 21.2 °C.
    const advice = targetAdvice(room([...Array<number>(42).fill(24), ...Array<number>(6).fill(21.2)], 21.2, 21), outdoor(5), NOW)!
    expect(advice.status).toBe('ok')
  })

  it('ignores a short airing dip', () => {
    const advice = targetAdvice(room([...day(19), 16], 16), outdoor(5), NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.marks).toBe(-1)
  })

  it('advises at least one mark', () => {
    expect(targetAdvice(room(day(17.3), 17.3), undefined, NOW)!.marks).toBe(1)
  })

  it('gives no advice to turn down when it is warm outside', () => {
    const advice = targetAdvice(room(day(24), 24), outdoor(22), NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.heatingOff).toBe(true)
    expect(advice.marks).toBeNull()
  })

  it('ignores a stale outdoor value', () => {
    expect(targetAdvice(room(day(24), 24), outdoor(22, 3 * 3600), NOW)!.marks).toBe(-6)
  })

  it('needs a few hours of data for advice', () => {
    const advice = targetAdvice(room([20, 20], 20), undefined, NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.marks).toBeNull()
  })

  it('is absent without a target', () => {
    expect(targetAdvice(room(day(20), 20, null), undefined, NOW)).toBeNull()
  })
})

describe('mouldSeverity', () => {
  const week = (share: number) => ({ threshold: 80, basis: 'surface' as const, share, hours: 168 })
  const air = (level: 'good' | 'warning' | 'critical') => ({
    absolute_humidity: 11.9,
    outdoor_absolute_humidity: 5.0,
    surface_humidity: 75,
    level,
    basis: 'surface' as const,
    ventilation: null,
    minutes: null,
  })
  it('rates the last 7 days: a quarter of the time above the limit is critical', () => {
    expect([0.05, 0.2, 0.3].map((share) => mouldWeekSeverity(week(share)))).toEqual(['good', 'warning', 'critical'])
  })
  it('takes the worse of now and the week', () => {
    expect(mouldSeverity(air('warning'), week(0))).toBe('warning')
    expect(mouldSeverity(air('good'), week(0.4))).toBe('critical')
    expect(mouldSeverity(null, null)).toBeNull()
  })
})

describe('signalBars', () => {
  it('maps dBm to bars', () => {
    expect([-60, -75, -85, -95].map(signalBars)).toEqual([4, 3, 2, 1])
  })
})

describe('banners', () => {
  const status = (state: Status['bluetooth']['state'], paired = true): Status => ({
    version: '0.4.0',
    started_at: NOW - 100,
    bluetooth: { state, since: NOW - 60, error: null, scanning_mode: 'active', last_advertisement: null },
    homekit: { paired, controllers: 1 },
    sensors: [],
    system: null,
    problems: [],
  })

  it('shows nothing when all is well', () => {
    expect(banners(status('running'), null)).toEqual([])
  })
  it('reports Bluetooth trouble and missing pairing', () => {
    expect(banners(status('failed', false), null).map((b) => [b.kind, b.severity])).toEqual([
      ['bluetooth', 'critical'],
      ['homekit', 'warning'],
    ])
  })
  it('reports recent under-voltage for a day', () => {
    const power = { ...status('running'), system: { cpu_temperature: 50, undervoltage: false, undervoltage_count: 1, last_undervoltage: NOW - 3600 } }
    expect(banners(power, null, NOW).map((b) => b.kind)).toEqual(['power'])
    expect(banners(power, null, NOW + 2 * 86400)).toEqual([])
  })
  it('only reports the lost connection while offline (the status is outdated)', () => {
    expect(banners(status('failed'), NOW).map((b) => b.kind)).toEqual(['offline'])
  })
})
