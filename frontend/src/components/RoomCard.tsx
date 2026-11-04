import type { OverviewSensor, SensorLive } from '../api'
import { HEATING_LIMIT, freshOutdoorTemperature, humidSeverity, signalBars, targetAdvice } from '../advice'
import { formatAgo, formatDelta, formatKelvin, formatMarks, formatPercent, formatValue } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  BatteryIcon,
  CheckIcon,
  CloudIcon,
  DropIcon,
  HomeIcon,
  SignalIcon,
  TargetIcon,
  WarningIcon,
} from './Icons'
import { severityFill } from '../severity'
import { SeverityIcon } from './Severity'
import { Sparkline } from './Sparkline'

interface Props {
  sensor: OverviewSensor
  outdoor: OverviewSensor | undefined
  /** Live state from /api/status, if available. */
  live: SensorLive | undefined
  color: string
  theme: Theme
  now: number
}

const STALE_SECONDS = { ble: 20 * 60, weather: 75 * 60 }

function TargetBlock({ sensor, outdoor, now }: { sensor: OverviewSensor; outdoor: OverviewSensor | undefined; now: number }) {
  const advice = targetAdvice(sensor, outdoor, now)
  if (!advice) return null
  const target = t('target', { value: formatValue(advice.target, 'temperature') })
  const deviation =
    advice.deviation === null || advice.status === 'ok' || advice.status === 'unknown'
      ? null
      : t(advice.status === 'warm' ? 'tooWarm' : 'tooCold', { value: formatKelvin(advice.deviation) })

  let icon = <TargetIcon className="size-4" />
  let headline = target
  let detail: string | null = null
  if (advice.status === 'ok') {
    icon = <CheckIcon className="size-4 text-good" />
    headline = t('onTarget')
    detail = target
  } else if (advice.marks !== null) {
    icon = advice.marks < 0 ? <ArrowDownIcon className="size-4" /> : <ArrowUpIcon className="size-4" />
    headline = t(advice.marks < 0 ? 'turnDown' : 'turnUp', { marks: formatMarks(Math.abs(advice.marks)) })
    detail = `${deviation} (${t('recent3h')}) · ${target}`
  } else if (deviation) {
    headline = `${deviation} (${t('recent3h')})`
    detail = target
  }

  return (
    <div className="flex items-start gap-3 border-t border-border pt-3 text-xs text-ink-2">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-wash text-ink" aria-hidden>
        {icon}
      </span>
      <div className="grid gap-0.5">
        <p className="text-[13px] font-medium text-ink">{headline}</p>
        {detail && <p>{detail}</p>}
        {advice.marks !== null && <p className="text-muted">{t('waitHint')}</p>}
        {advice.heatingOff && (
          <p className="text-muted">{t('heatingOff', { limit: formatValue(HEATING_LIMIT, 'temperature') })}</p>
        )}
      </div>
    </div>
  )
}

function HumidBlock({ sensor }: { sensor: OverviewSensor }) {
  const humid = sensor.humid
  if (!humid) return null
  const severity = humidSeverity(humid)
  const basis = humid.hours >= 7 * 24 - 1 ? t('humidBasis') : t('humidBasisShort', { hours: humid.hours })
  return (
    <div className="grid gap-1.5 border-t border-border pt-3 text-xs text-ink-2">
      <p className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span>
          {t('humidLabel', { threshold: humid.threshold })}:{' '}
          <span className="font-medium text-ink">{t('humidShare', { share: formatPercent(humid.share) })}</span>
        </span>
        <span className="text-muted">{basis}</span>
      </p>
      <div
        className="h-2 overflow-hidden rounded-full bg-wash"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(humid.share * 100)}
        aria-label={t('humidLabel', { threshold: humid.threshold })}
      >
        <div className={`h-full rounded-full ${severityFill[severity]}`} style={{ width: `${Math.max(2, humid.share * 100)}%` }} />
      </div>
      <p className="flex items-center gap-1.5 text-ink">
        <SeverityIcon severity={severity} decorative />
        {t(`humid_${severity}`)}
      </p>
    </div>
  )
}

export function RoomCard({ sensor, outdoor, live, color, theme, now }: Props) {
  const latest = sensor.latest
  const lastSeen = live?.last_seen ?? latest?.ts ?? null
  const stale = live ? !live.reporting : !latest || now - latest.ts > STALE_SECONDS[sensor.kind]
  const outsideTemperature = freshOutdoorTemperature(outdoor, now)
  const delta =
    sensor.kind === 'ble' && latest?.temperature != null && outsideTemperature !== null
      ? latest.temperature - outsideTemperature
      : null
  const today = sensor.today
  const KindIcon = sensor.kind === 'weather' ? CloudIcon : HomeIcon

  return (
    <article className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="flex items-center justify-between gap-2">
        <h2 className="flex min-w-0 items-center gap-2 text-[15px] font-medium text-ink">
          <span className="size-2.5 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
          <span className="truncate">{sensor.name}</span>
          <KindIcon className="size-4 shrink-0 text-muted" />
        </h2>
        <span className="flex items-center gap-3 text-xs text-ink-2 tabular">
          {live?.rssi != null && (
            <span className="flex items-center gap-1" title={t('signal', { rssi: live.rssi })}>
              <SignalIcon bars={signalBars(live.rssi)} className="size-4" />
              <span className="sr-only">{t('signal', { rssi: live.rssi })}</span>
            </span>
          )}
          {latest?.battery != null && (
            <span className="flex items-center gap-1" title={t('battery')}>
              <BatteryIcon level={latest.battery} className="size-5" />
              {latest.battery} %
            </span>
          )}
        </span>
      </header>

      <div className="flex items-end justify-between gap-3">
        <p className="text-5xl leading-none font-semibold tracking-tight text-ink">
          {formatValue(latest?.temperature, 'temperature')}
        </p>
        <div className="text-right text-sm text-ink-2">
          <p className="flex items-center justify-end gap-1">
            <DropIcon className="size-4 text-muted" />
            <span>{formatValue(latest?.humidity, 'humidity')}</span>
          </p>
          <p className="text-xs text-muted">
            {t('dewPoint')} {formatValue(latest?.dew_point, 'temperature')}
          </p>
        </div>
      </div>

      <Sparkline
        values={sensor.spark.map((s) => s[1])}
        color={color}
        surface={theme.surface}
        label={`${sensor.name}: ${t('temperature')} 24 h`}
      />

      <footer className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-2">
        <span className="tabular">
          {t('today')} {formatValue(today?.[0], 'temperature')} – {formatValue(today?.[2], 'temperature')}
        </span>
        {delta !== null && (
          <span className="tabular">
            {formatDelta(delta, 'temperature')} {t('vsOutdoor')}
          </span>
        )}
      </footer>

      <TargetBlock sensor={sensor} outdoor={outdoor} now={now} />
      <HumidBlock sensor={sensor} />

      {stale ? (
        <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
          <WarningIcon className="size-4 text-warning" />
          {t('stale')}
          {lastSeen !== null && (
            <span className="font-normal text-muted">
              · {t('lastSeen')} {formatAgo(lastSeen, now)}
            </span>
          )}
        </p>
      ) : (
        lastSeen !== null && <p className="text-xs text-muted">{formatAgo(lastSeen, now)}</p>
      )}
    </article>
  )
}
