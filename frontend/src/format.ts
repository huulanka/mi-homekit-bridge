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
  return `${signed.format(value)} ${metric === 'temperature' ? 'K' : 'pp'}`
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
  return t('hoursAgo', { n: Math.round(minutes / 60) })
}

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}
