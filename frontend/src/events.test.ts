import { describe, expect, it } from 'vitest'
import { describeEvent, eventSeverity, groupEvents } from './events'

describe('describeEvent', () => {
  const names = { 'A4:C1:38:00:00:02': 'Bedroom' }
  it('fills in the sensor name and parameters', () => {
    const text = describeEvent({ ts: 0, kind: 'sensor_back', sensor_id: 'A4:C1:38:00:00:02', data: { minutes: 90 } }, names)
    expect(text).toContain('Bedroom')
    expect(text).toContain('90')
  })
  it('falls back for unknown kinds', () => {
    expect(describeEvent({ ts: 0, kind: 'future_thing', sensor_id: null, data: {} }, names)).toContain('future_thing')
  })
  it('rates outages and recoveries', () => {
    expect(eventSeverity('bluetooth_reset')).toBe('critical')
    expect(eventSeverity('sensor_lost')).toBe('warning')
    expect(eventSeverity('scan_recovered')).toBe('good')
    expect(eventSeverity('started')).toBeUndefined()
  })
})

describe('groupEvents', () => {
  const e = (ts: number, kind: string, data: Record<string, string | number> = {}) => ({ ts, kind, sensor_id: null, data })

  it('turns deploys into restarts and updates, newest first', () => {
    // The real sequence of 2026-11-04 (oldest first), as the API returns it newest first.
    const events = [
      e(0, 'started', { version: '0.4.0' }),
      e(100, 'stopped'),
      e(105, 'scan_failed', { error: 'passive' }),
      e(105, 'started', { version: '0.4.0' }),
      e(160, 'stopped'),
      e(165, 'started', { version: '0.4.0' }),
      e(600, 'stopped'),
      e(605, 'started', { version: '0.4.1' }),
      e(1500, 'bluetooth_reset'),
      e(1516, 'started', { version: '0.4.1' }),
    ].reverse()
    const grouped = groupEvents(events)
    expect(grouped.map((g) => [g.kind, g.data])).toEqual([
      ['started', { version: '0.4.1' }], // after a reset: no stop before it
      ['bluetooth_reset', {}],
      ['update', { version: '0.4.1', previous: '0.4.0' }],
      ['restart', { version: '0.4.0', count: 2 }],
      ['scan_failed', { error: 'passive' }],
      ['started', { version: '0.4.0' }],
    ])
    expect(events).toHaveLength(10) // not modified
  })

  it('describes merged restarts with their count', () => {
    const text = describeEvent(e(0, 'restart', { version: '0.5.0', count: 3 }), {})
    expect(text).toContain('3')
    expect(text).toContain('0.5.0')
    expect(describeEvent(e(0, 'update', { version: '0.5.0', previous: '0.4.1' }), {})).toContain('0.4.1')
    expect(eventSeverity('undervoltage')).toBe('warning')
  })
})
