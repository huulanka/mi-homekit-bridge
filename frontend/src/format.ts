import { locale, t } from './i18n'
import type { Metric } from './api'

const oneDecimal = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const noDecimal = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
const signed = new Intl.NumberFormat(locale, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

export const unit: Record<Metric, string> = { temperature: '°C', humidity: '%', absolute: 'g/m³' }

export function formatValue(value: number | null | undefined, metric: Metric): string {
  if (value === null || value === undefined) return '–'
  const number = metric === 'humidity' ? noDecimal.format(value) : oneDecimal.format(value)
  return `${number} ${unit[metric]}`
}

export function formatDelta(value: number | null | undefined, metric: Metric): string {
  if (value === null || value === undefined) return '–'
  const suffix = metric === 'temperature' ? 'K' : metric === 'absolute' ? 'g/m³' : t('deltaUnitHumidity')
  return `${signed.format(value)} ${suffix}`
}

/** A plain number with up to one decimal, e.g. "12,4". */
export const formatNumber = (value: number, digits = 1) =>
  new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value)

/** Minutes as "35 Min." or "1 Std. 5 Min.". */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) return t('minutes', { n: Math.round(minutes) })
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes - hours * 60)
  return rest ? t('hoursMinutes', { h: hours, m: rest }) : t('hours', { n: hours })
}

/** A temperature difference without sign, e.g. "1,5 °C". */
export function formatKelvin(value: number): string {
  return `${oneDecimal.format(Math.abs(value))} °C`
}

const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
export const formatPercent = (share: number) => percent.format(share)

/** Marks on a thermostat dial, e.g. "1 Strich", "2 Striche". */
export function formatMarks(count: number): string {
  return count === 1 ? t('markOne') : t('markMany', { n: count })
}

const timeFormat = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' })
const dateTimeFormat = new Intl.DateTimeFormat(locale, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})
const dateFormat = new Intl.DateTimeFormat(locale, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
const shortDate = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' })

export const formatTime = (ts: number) => timeFormat.format(ts * 1000)
export const formatDateTime = (ts: number) => dateTimeFormat.format(ts * 1000)
export const formatDate = (ts: number) => dateFormat.format(ts * 1000)
export const formatShortDate = (date: Date) => shortDate.format(date)

export function formatAgo(ts: number, now: number): string {
  const minutes = Math.max(0, Math.round((now - ts) / 60))
  if (minutes < 2) return t('justNow')
  if (minutes < 120) return t('minutesAgo', { n: minutes })
  if (minutes < 48 * 60) return t('hoursAgo', { n: Math.round(minutes / 60) })
  return t('daysAgo', { n: Math.round(minutes / 1440) })
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}
