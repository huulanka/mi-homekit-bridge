import { describe, expect, it } from 'vitest'
import { describeEvent, eventSeverity } from './events'

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
