import { locale, t } from './i18n'
import type { Metric } from './api'

const oneDecimal = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const noDecimal = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
const signed = new Intl.NumberFormat(locale, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})

export const unit: Record<Metric, string> = { temperature: '°C', humidity: '%' }

export function formatValue(value: number | null | undefined, metric: Metric): string {
  if (value === null || value === undefined) return '–'
  const number = metric === 'temperature' ? oneDecimal.format(value) : noDecimal.format(value)
  return metric === 'temperature' ? `${number} °C` : `${number} %`
}

export function formatDelta(value: number | null | undefined, metric: Metric): string {
  if (value === null || value === undefined) return '–'
  return `${signed.format(value)} ${metric === 'temperature' ? 'K' : t('deltaUnitHumidity')}`
}

/** A temperature difference without sign, e.g. "1,5 °C". */
export function formatKelvin(value: number): string {
  return `${oneDecimal.format(Math.abs(value))} °C`
}

const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 })
export const formatPercent = (share: number) => percent.format(share)

const FRACTIONS: Record<number, string> = { 0: '', 0.25: '¼', 0.5: '½', 0.75: '¾' }

/** Quarter steps as text: 0.75 -> "¾", 2.5 -> "2½". */
export function formatFraction(value: number): string {
  const whole = Math.floor(value)
  const fraction = FRACTIONS[Math.round((value - whole) * 4) / 4] ?? ''
  return whole === 0 && fraction ? fraction : `${whole}${fraction}`
}

/** A number of dial steps, e.g. "½ Stufe", "1¼ Stufen". */
export function formatSteps(steps: number): string {
  const amount = Math.abs(steps)
  return `${formatFraction(amount)} ${amount > 1 ? t('stepMany') : t('stepOne')}`
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
