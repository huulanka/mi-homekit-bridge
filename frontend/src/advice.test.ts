import { describe, expect, it } from 'vitest'
import type { OverviewSensor, Status } from './api'
import { banners, dialFor, humidSeverity, signalBars, targetAdvice } from './advice'

const NOW = 1_800_000_000

function room(temps: (number | null)[], latest: number | null, target: number | null = 18): OverviewSensor {
  return {
    id: 'A',
    name: 'Bedroom',
    kind: 'ble',
    target_temperature: target,
    latest: { ts: NOW, temperature: latest, humidity: 60, battery: null, dew_point: null },
    today: null,
    spark: temps.map((t, i) => [NOW - (temps.length - i) * 1800, t, null]),
    humid: null,
  }
}

function outdoor(temperature: number, age = 600): OverviewSensor {
  return { ...room([], temperature, null), id: 'weather', kind: 'weather', latest: { ts: NOW - age, temperature, humidity: 80, battery: null, dew_point: null } }
}

const day = (t: number) => Array<number>(48).fill(t)

describe('dialFor', () => {
  it('follows the rule of thumb in half steps', () => {
    expect(dialFor(20)).toBe(3)
    expect(dialFor(18)).toBe(2.5)
    expect(dialFor(12)).toBe(1)
    expect(dialFor(5)).toBe(1)
    expect(dialFor(30)).toBe(5)
  })
})

describe('targetAdvice', () => {
  it('is on target within half a kelvin', () => {
    const advice = targetAdvice(room(day(18.4), 18.2), outdoor(5), NOW)!
    expect(advice.status).toBe('ok')
    expect(advice.steps).toBeNull()
  })

  it('advises turning down by the 24-hour average, not the current value', () => {
    // Airing just now (16 °C), but on average 3 K too warm.
    const advice = targetAdvice(room(day(21), 16), outdoor(5), NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.now).toBe(-2)
    expect(advice.average).toBe(3)
    expect(advice.steps).toBe(-0.75)
    expect(advice.dial).toBe(2.5)
  })

  it('advises at least a quarter step', () => {
    expect(targetAdvice(room(day(17.3), 17.3), undefined, NOW)!.steps).toBe(0.25)
  })

  it('gives no dial advice outside the heating season', () => {
    const advice = targetAdvice(room(day(24), 24), outdoor(22), NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.steps).toBeNull()
  })

  it('ignores a stale outdoor value', () => {
    expect(targetAdvice(room(day(24), 24), outdoor(22, 3 * 3600), NOW)!.steps).toBe(-1.5)
  })

  it('needs a few hours of data for advice', () => {
    const advice = targetAdvice(room([20, 20], 20), undefined, NOW)!
    expect(advice.status).toBe('warm')
    expect(advice.steps).toBeNull()
  })

  it('is absent without a target', () => {
    expect(targetAdvice(room(day(20), 20, null), undefined, NOW)).toBeNull()
  })
})

describe('humidSeverity', () => {
  it('maps the share to a status', () => {
    expect(humidSeverity({ threshold: 60, share: 0.05, hours: 168 })).toBe('good')
    expect(humidSeverity({ threshold: 60, share: 0.33, hours: 168 })).toBe('warning')
    expect(humidSeverity({ threshold: 60, share: 0.7, hours: 168 })).toBe('critical')
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
  it('only reports the lost connection while offline (the status is outdated)', () => {
    expect(banners(status('failed'), NOW).map((b) => b.kind)).toEqual(['offline'])
  })
})
