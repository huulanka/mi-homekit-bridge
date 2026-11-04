import { useId, useState, type ReactNode } from 'react'
import type { OverviewSensor, SensorLive } from '../api'
import {
  HEATING_LIMIT,
  freshOutdoorTemperature,
  mouldSeverity,
  mouldWeekSeverity,
  signalBars,
  targetAdvice,
  type Severity,
} from '../advice'
import {
  formatAgo,
  formatDelta,
  formatKelvin,
  formatMarks,
  formatMinutes,
  formatNumber,
  formatPercent,
  formatTime,
  formatValue,
} from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import {
  AirIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  BatteryIcon,
  CheckIcon,
  ChevronIcon,
  CloudIcon,
  DropIcon,
  HomeIcon,
  RainIcon,
  SignalIcon,
  SunIcon,
  TargetIcon,
  WarningIcon,
  WindIcon,
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
/** A battery level older than this is shown as outdated. */
const BATTERY_OLD_SECONDS = 7 * 86400

type ChipKey = 'target' | 'mould' | 'air'

interface Chip {
  key: ChipKey
  icon: ReactNode
  label: string
  panel: ReactNode
}

function targetChip(sensor: OverviewSensor, outdoor: OverviewSensor | undefined, now: number): Chip | null {
  const advice = targetAdvice(sensor, outdoor, now)
  if (!advice) return null
  const target = t('target', { value: formatValue(advice.target, 'temperature') })
  const deviation =
    advice.deviation === null || advice.status === 'ok' || advice.status === 'unknown'
      ? null
      : t(advice.status === 'warm' ? 'tooWarm' : 'tooCold', { value: formatKelvin(advice.deviation) })

  let icon = <TargetIcon className="size-4" />
  let label = target
  let headline = target
  let detail: string | null = null
  if (advice.status === 'ok') {
    icon = <CheckIcon className="size-4 text-good" />
    label = headline = t('onTarget')
    detail = target
  } else if (advice.marks !== null) {
    const marks = formatMarks(Math.abs(advice.marks))
    icon = advice.marks < 0 ? <ArrowDownIcon className="size-4" /> : <ArrowUpIcon className="size-4" />
    label = t(advice.marks < 0 ? 'chipMarksDown' : 'chipMarksUp', { marks })
    headline = t(advice.marks < 0 ? 'turnDown' : 'turnUp', { marks })
    detail = `${deviation} (${t('recent3h')}) · ${target}`
  } else if (deviation) {
    label = deviation
    headline = `${deviation} (${t('recent3h')})`
    detail = target
  }
  return {
    key: 'target',
    icon,
    label,
    panel: (
      <>
        <p className="font-medium text-ink">{headline}</p>
        {detail && <p>{detail}</p>}
        {advice.marks !== null && <p className="text-muted">{t('waitHint')}</p>}
        {advice.heatingOff && <p className="text-muted">{t('heatingOff', { limit: formatValue(HEATING_LIMIT, 'temperature') })}</p>}
      </>
    ),
  }
}

function Meter({ share, severity, label }: { share: number; severity: Severity; label: string }) {
  return (
    <div
      className="h-2 overflow-hidden rounded-full bg-wash"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(share * 100)}
      aria-label={label}
    >
      <div className={`h-full rounded-full ${severityFill[severity]}`} style={{ width: `${Math.max(2, share * 100)}%` }} />
    </div>
  )
}

function mouldChip(sensor: OverviewSensor, outdoor: OverviewSensor | undefined): Chip | null {
  const { air, mould } = sensor
  const severity = mouldSeverity(air, mould)
  if (!severity) return null
  const surface = air?.basis === 'surface' ? air.surface_humidity : null
  const room = sensor.latest?.humidity ?? null
  const value = formatValue(surface ?? room, 'humidity')
  const label =
    air?.basis === 'room' ? t('mouldChipRoom', { value }) : severity === 'good' ? t('mouldChipOk') : t('mouldChip', { value })
  const outside = outdoor?.latest?.temperature ?? null
  return {
    key: 'mould',
    icon: <SeverityIcon severity={severity} decorative />,
    label,
    panel: (
      <>
        <p className="flex items-center gap-1.5 font-medium text-ink">
          <SeverityIcon severity={severity} decorative />
          {t(`mould_${severity}`)}
        </p>
        <p>{air?.basis === 'surface' ? t('mouldNow', { value }) : t('mouldRoomNow', { value })}</p>
        {mould && (
          <div className="grid gap-1">
            <p className="flex flex-wrap items-baseline justify-between gap-x-2">
              <span>{t('mouldShare', { threshold: mould.threshold, share: formatPercent(mould.share) })}</span>
              <span className="text-muted">{mould.hours >= 7 * 24 - 1 ? t('basis7d') : t('basisHours', { hours: mould.hours })}</span>
            </p>
            <Meter
              share={mould.share}
              severity={mouldWeekSeverity(mould)}
              label={t('mouldShare', { threshold: mould.threshold, share: formatPercent(mould.share) })}
            />
          </div>
        )}
        {air?.basis === 'surface' && sensor.surface_factor !== null && (
          <p className="text-muted">
            {t('mouldMethod', { factor: formatNumber(sensor.surface_factor, 2), outdoor: formatValue(outside, 'temperature') })}
          </p>
        )}
      </>
    ),
  }
}

function airChip(sensor: OverviewSensor): Chip | null {
  const { air, airings } = sensor
  if (!air?.ventilation && !airings) return null
  const inside = formatValue(air?.absolute_humidity, 'absolute')
  const outside = formatValue(air?.outdoor_absolute_humidity, 'absolute')
  const count = airings?.today ?? 0
  let label = t('airChipFine')
  let advice: ReactNode = <p className="font-medium text-ink">{t('airFine')}</p>
  if (air?.ventilation === 'recommended') {
    label = t('airChipVentilate', { minutes: air.minutes ?? 10 })
    advice = (
      <>
        <p className="font-medium text-ink">{t('airRecommended', { minutes: air.minutes ?? 10 })}</p>
        <p>{t('airDrier', { inside, outside })}</p>
      </>
    )
  } else if (air?.ventilation === 'avoid') {
    label = t('airChipAvoid')
    advice = <p className="font-medium text-ink">{t('airAvoid', { outside })}</p>
  } else if (count > 0) {
    label = t('airChipAired', { n: count })
  }
  const last = airings?.last
  return {
    key: 'air',
    icon: <AirIcon className="size-4" />,
    label,
    panel: (
      <>
        {advice}
        {airings && (
          <p>
            {last
              ? t('airedToday', {
                  n: count,
                  time: formatTime(last.start),
                  drop: formatKelvin(last.drop),
                  recovery:
                    last.recovery_minutes === null
                      ? t('notRecovered')
                      : t('recoveredAfter', { duration: formatMinutes(last.recovery_minutes) }),
                })
              : t('airedNone')}
          </p>
        )}
        <p className="text-muted">{t('airingDetection')}</p>
      </>
    ),
  }
}

function Chips({ chips }: { chips: Chip[] }) {
  const [open, setOpen] = useState<ChipKey | null>(null)
  const id = useId()
  const active = chips.find((chip) => chip.key === open)
  if (chips.length === 0) return null
  return (
    <div className="grid gap-2 border-t border-border pt-3">
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            aria-expanded={open === chip.key}
            aria-controls={`${id}-${chip.key}`}
            onClick={() => setOpen(open === chip.key ? null : chip.key)}
            className={
              'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs whitespace-nowrap transition-colors ' +
              (open === chip.key ? 'border-ink/25 bg-wash text-ink' : 'border-border text-ink hover:bg-wash')
            }
          >
            {chip.icon}
            {chip.label}
            <ChevronIcon className={`size-3.5 text-muted transition-transform ${open === chip.key ? 'rotate-180' : ''}`} />
          </button>
        ))}
      </div>
      {active && (
        <div id={`${id}-${active.key}`} className="grid gap-1.5 rounded-xl bg-wash/60 px-3 py-2.5 text-xs text-ink-2">
          {active.panel}
        </div>
      )}
    </div>
  )
}

function WeatherLine({ sensor }: { sensor: OverviewSensor }) {
  const latest = sensor.latest
  if (!latest || (latest.radiation == null && latest.wind == null && latest.precipitation == null)) return null
  const items = [
    { icon: SunIcon, label: t('sunNow'), value: latest.radiation, text: `${formatNumber(latest.radiation ?? 0, 0)} W/m²` },
    { icon: WindIcon, label: t('windNow'), value: latest.wind, text: `${formatNumber(latest.wind ?? 0, 0)} km/h` },
    { icon: RainIcon, label: t('rainNow'), value: latest.precipitation, text: `${formatNumber(latest.precipitation ?? 0)} mm/h` },
  ]
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2 tabular">
      {items
        .filter((item) => item.value != null)
        .map(({ icon: Icon, label, text }) => (
          <span key={label} className="flex items-center gap-1" title={label}>
            <Icon className="size-4 text-muted" />
            <span className="sr-only">{label}</span>
            {text}
          </span>
        ))}
    </p>
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
  const battery = sensor.battery
  const batteryOld = battery !== null && now - battery.ts > BATTERY_OLD_SECONDS
  const chips = [targetChip(sensor, outdoor, now), mouldChip(sensor, outdoor), airChip(sensor)].filter(
    (chip): chip is Chip => chip !== null,
  )

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
          {battery && (
            <span
              className={`flex items-center gap-1 ${batteryOld ? 'text-muted' : ''}`}
              title={t(batteryOld ? 'batteryOld' : 'batteryAge', { level: battery.level, age: formatAgo(battery.ts, now) })}
            >
              <BatteryIcon level={battery.level} className="size-5" />
              {battery.level} %{batteryOld ? '?' : ''}
              <span className="sr-only">
                {t(batteryOld ? 'batteryOld' : 'batteryAge', { level: battery.level, age: formatAgo(battery.ts, now) })}
              </span>
            </span>
          )}
        </span>
      </header>

      <div className="flex items-end justify-between gap-3">
        <p className="text-5xl leading-none font-semibold tracking-tight whitespace-nowrap text-ink">
          {formatValue(latest?.temperature, 'temperature')}
        </p>
        <div className="text-right text-sm text-ink-2">
          <p className="flex items-center justify-end gap-1">
            <DropIcon className="size-4 text-muted" />
            <span>{formatValue(latest?.humidity, 'humidity')}</span>
          </p>
          <p className="text-xs whitespace-nowrap text-muted tabular">{formatValue(latest?.absolute_humidity, 'absolute')}</p>
          <p className="text-xs whitespace-nowrap text-muted tabular">
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

      {sensor.kind === 'weather' && <WeatherLine sensor={sensor} />}
      <Chips chips={chips} />

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
