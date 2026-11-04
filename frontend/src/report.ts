// Aggregations of the daily statistics (unit-tested in report.test.ts).
import type { Daily, OutdoorDay, RoomDay } from './api'

export type DailySensor = Daily['sensors'][number]

export const isRoomDay = (day: RoomDay | OutdoorDay): day is RoomDay => 'on_target' in day
export const isOutdoorDay = (day: RoomDay | OutdoorDay): day is OutdoorDay => 'heating_degrees' in day

function weighted(days: RoomDay[], value: (day: RoomDay) => number | null): number | null {
  let sum = 0
  let weight = 0
  for (const day of days) {
    const v = value(day)
    if (v === null) continue
    sum += v * day.samples
    weight += day.samples
  }
  return weight ? sum / weight : null
}

function median(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle]! : (sorted[middle - 1]! + sorted[middle]!) / 2
}

export interface RoomWeek {
  days: number
  temperature: number | null
  onTarget: number | null
  /** Hours with mould risk (shares of 24 h per day). */
  mouldHours: number | null
  airingsPerDay: number | null
  recoveryMinutes: number | null
  absolute: number | null
}

export interface OutdoorWeek {
  days: number
  temperature: number | null
  heatingDegrees: number | null
  precipitation: number | null
}

export function roomWeek(days: RoomDay[]): RoomWeek {
  const recoveries = days.map((d) => d.recovery_minutes).filter((v): v is number => v !== null)
  const mould = days.filter((d) => d.mould !== null)
  return {
    days: days.length,
    temperature: weighted(days, (d) => d.temperature_avg),
    onTarget: weighted(days, (d) => d.on_target),
    mouldHours: mould.length ? mould.reduce((sum, d) => sum + d.mould! * 24, 0) : null,
    airingsPerDay: days.length ? days.reduce((sum, d) => sum + d.airings, 0) / days.length : null,
    recoveryMinutes: median(recoveries),
    absolute: weighted(days, (d) => d.absolute_avg),
  }
}

export function outdoorWeek(days: OutdoorDay[]): OutdoorWeek {
  const sum = (value: (d: OutdoorDay) => number | null) => {
    const values = days.map(value).filter((v): v is number => v !== null)
    return values.length ? values.reduce((a, b) => a + b, 0) : null
  }
  const temperatures = days.map((d) => d.temperature_avg).filter((v): v is number => v !== null)
  return {
    days: days.length,
    temperature: temperatures.length ? temperatures.reduce((a, b) => a + b, 0) / temperatures.length : null,
    heatingDegrees: sum((d) => d.heating_degrees),
    precipitation: sum((d) => d.precipitation),
  }
}

/** ISO date `days` days before `day` (both YYYY-MM-DD, local calendar). */
export function shiftDay(day: string, days: number): string {
  const date = new Date(`${day}T12:00:00`)
  date.setDate(date.getDate() + days)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export interface WeeklyReport {
  /** First and last day of the reported week (the 7 complete days before today). */
  start: string
  end: string
  rooms: { sensor: DailySensor; current: RoomWeek; previous: RoomWeek | null }[]
  outdoor: { sensor: DailySensor; current: OutdoorWeek; previous: OutdoorWeek | null } | null
}

/** Minimum days with data for the week before to be compared. */
const MIN_PREVIOUS_DAYS = 3

/** The last 7 complete days compared with the 7 days before; null without data. */
export function weeklyReport(daily: Daily, today: string): WeeklyReport | null {
  const end = shiftDay(today, -1)
  const start = shiftDay(today, -7)
  const previousStart = shiftDay(today, -14)
  const inWeek = (day: string) => day >= start && day <= end
  const inPrevious = (day: string) => day >= previousStart && day < start

  const rooms: WeeklyReport['rooms'] = []
  let outdoor: WeeklyReport['outdoor'] = null
  for (const sensor of daily.sensors) {
    if (sensor.kind === 'weather') {
      const days = sensor.days.filter(isOutdoorDay)
      const current = days.filter((d) => inWeek(d.day))
      if (current.length === 0) continue
      const before = days.filter((d) => inPrevious(d.day))
      outdoor = { sensor, current: outdoorWeek(current), previous: before.length >= MIN_PREVIOUS_DAYS ? outdoorWeek(before) : null }
    } else {
      const days = sensor.days.filter(isRoomDay)
      const current = days.filter((d) => inWeek(d.day))
      if (current.length === 0) continue
      const before = days.filter((d) => inPrevious(d.day))
      rooms.push({ sensor, current: roomWeek(current), previous: before.length >= MIN_PREVIOUS_DAYS ? roomWeek(before) : null })
    }
  }
  return rooms.length || outdoor ? { start, end, rooms, outdoor } : null
}

export interface Period {
  /** YYYY-MM-DD (day) or YYYY-MM (month) */
  key: string
  cold: number
  onTarget: number
  warm: number
}

/** Time in the target band per day, or per month for long ranges (weighted by samples). */
export function targetPeriods(days: RoomDay[], by: 'day' | 'month'): Period[] {
  const groups = new Map<string, RoomDay[]>()
  for (const day of days) {
    if (day.on_target === null) continue
    const key = by === 'day' ? day.day : day.day.slice(0, 7)
    groups.set(key, [...(groups.get(key) ?? []), day])
  }
  return [...groups.entries()].map(([key, group]) => ({
    key,
    cold: weighted(group, (d) => d.cold) ?? 0,
    onTarget: weighted(group, (d) => d.on_target) ?? 0,
    warm: weighted(group, (d) => d.warm) ?? 0,
  }))
}

/** Heating degree days per day, or summed per month. */
export function degreeDayPeriods(days: OutdoorDay[], by: 'day' | 'month'): { key: string; degrees: number; temperature: number | null }[] {
  const groups = new Map<string, OutdoorDay[]>()
  for (const day of days) {
    if (day.heating_degrees === null) continue
    const key = by === 'day' ? day.day : day.day.slice(0, 7)
    groups.set(key, [...(groups.get(key) ?? []), day])
  }
  return [...groups.entries()].map(([key, group]) => {
    const temperatures = group.map((d) => d.temperature_avg).filter((v): v is number => v !== null)
    return {
      key,
      degrees: group.reduce((sum, d) => sum + (d.heating_degrees ?? 0), 0),
      temperature: temperatures.length ? temperatures.reduce((a, b) => a + b, 0) / temperatures.length : null,
    }
  })
}

/** Local calendar date (YYYY-MM-DD) of a UTC epoch timestamp. */
export function localDay(ts: number): string {
  const date = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
