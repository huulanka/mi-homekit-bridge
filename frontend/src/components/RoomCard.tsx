import type { OverviewSensor } from '../api'
import { formatAgo, formatDelta, formatValue } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { BatteryIcon, CloudIcon, DropIcon, HomeIcon, WarningIcon } from './Icons'
import { Sparkline } from './Sparkline'

interface Props {
  sensor: OverviewSensor
  outdoor: OverviewSensor | undefined
  color: string
  theme: Theme
  now: number
}

const STALE_SECONDS = { ble: 20 * 60, weather: 75 * 60 }

export function RoomCard({ sensor, outdoor, color, theme, now }: Props) {
  const latest = sensor.latest
  const stale = !latest || now - latest.ts > STALE_SECONDS[sensor.kind]
  const outsideTemperature = outdoor?.latest?.temperature ?? null
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
        {latest?.battery != null && (
          <span className="flex items-center gap-1 text-xs text-ink-2 tabular" title={t('battery')}>
            <BatteryIcon level={latest.battery} className="size-5" />
            {latest.battery} %
          </span>
        )}
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

      {stale ? (
        <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
          <WarningIcon className="size-4 text-warning" />
          {t('stale')}
          {latest && (
            <span className="font-normal text-muted">
              · {t('lastSeen')} {formatAgo(latest.ts, now)}
            </span>
          )}
        </p>
      ) : (
        latest && <p className="text-xs text-muted">{formatAgo(latest.ts, now)}</p>
      )}
    </article>
  )
}
