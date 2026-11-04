import { useMemo, useState } from 'react'
import { banners } from './advice'
import {
  pick,
  type Daily,
  type Events,
  type Heatmap,
  type Metric,
  type Overview,
  type Profile,
  type RangeKey,
  type Series,
  type Status,
} from './api'
import { CalendarChart } from './charts/CalendarChart'
import { DegreeDaysChart } from './charts/DegreeDaysChart'
import { DeltaChart } from './charts/DeltaChart'
import { HeatmapChart } from './charts/HeatmapChart'
import { HistoryChart } from './charts/HistoryChart'
import { MouldChart } from './charts/MouldChart'
import { ProfileChart } from './charts/ProfileChart'
import { TargetChart } from './charts/TargetChart'
import { WeatherChart } from './charts/WeatherChart'
import { ChartCard } from './components/ChartCard'
import { FilterBar, RANGES } from './components/FilterBar'
import { EventsCard } from './components/EventsCard'
import { DownloadIcon } from './components/Icons'
import { RoomCard } from './components/RoomCard'
import { StatusBanners } from './components/StatusBanner'
import { WeeklyReport } from './components/WeeklyReport'
import { HOURS, computeDeltas, dayValue, hasWeather, heatmapCells, mouldSensors, profileValues } from './data'
import {
  formatDate,
  formatDateTime,
  formatDelta,
  formatNumber,
  formatPercent,
  formatShortDate,
  formatTime,
  formatValue,
} from './format'
import { locale, t, type MessageKey } from './i18n'
import {
  degreeDayPeriods,
  isOutdoorDay,
  isRoomDay,
  localDay,
  targetPeriods,
  weeklyReport,
  type DailySensor,
} from './report'
import { colorFor, useTheme } from './theme'
import { useApi } from './useApi'

const PROFILE_DAYS: Record<RangeKey, number> = { '24h': 7, '7d': 7, '30d': 30, '1y': 365, all: 365 }
const HEATMAP_DAYS: Record<RangeKey, number> = { '24h': 14, '7d': 14, '30d': 30, '1y': 90, all: 90 }
const DAILY_DAYS: Record<RangeKey, number> = { '24h': 15, '7d': 15, '30d': 31, '1y': 366, all: 366 }
/** Days shown in the per-day charts (time in target, degree days). */
const PERIOD_DAYS: Record<RangeKey, number> = { '24h': 7, '7d': 7, '30d': 31, '1y': 366, all: 366 }

const monthFormat = new Intl.DateTimeFormat(locale, { month: 'short', year: '2-digit' })
const periodLabel = (key: string) =>
  key.length === 7 ? monthFormat.format(new Date(`${key}-15T12:00:00`)) : formatShortDate(new Date(`${key}T12:00:00`))

function usePersisted<T extends string>(key: string, allowed: readonly T[], fallback: T) {
  const [value, setValue] = useState<T>(() => {
    const stored = localStorage.getItem(key)
    return allowed.includes(stored as T) ? (stored as T) : fallback
  })
  const update = (next: T) => {
    localStorage.setItem(key, next)
    setValue(next)
  }
  return [value, update] as const
}

export default function App() {
  const theme = useTheme()
  const [range, setRange] = usePersisted<RangeKey>('range', RANGES, '7d')
  const [metric, setMetric] = usePersisted<Metric>('metric', ['temperature', 'humidity', 'absolute'], 'temperature')

  const overview = useApi<Overview>('/api/overview', 60_000)
  const series = useApi<Series>(`/api/series?range=${range}`, 300_000)
  const profile = useApi<Profile>(`/api/profile?days=${PROFILE_DAYS[range]}`, 900_000)
  const heatmap = useApi<Heatmap>(`/api/heatmap?days=${HEATMAP_DAYS[range]}`, 900_000)
  const status = useApi<Status>('/api/status', 30_000)
  const events = useApi<Events>('/api/events', 120_000)
  const report = useApi<Daily>('/api/daily?days=15', 900_000)
  const daily = useApi<Daily>(`/api/daily?days=${DAILY_DAYS[range]}`, 900_000)

  // A sensor keeps its color slot whatever is filtered: assigned by overview order.
  const colors = useMemo(() => {
    const map: Record<string, string> = {}
    overview.data?.sensors.forEach((sensor, index) => (map[sensor.id] = colorFor(theme, index)))
    return map
  }, [overview.data, theme])

  const sensors = overview.data?.sensors ?? []
  const outdoor = sensors.find((s) => s.kind === 'weather')
  const hasData = sensors.some((s) => s.latest)
  const now = overview.data?.generated_at ?? 0
  // A failed refresh while data is shown means the bridge is unreachable. The
  // status endpoint does not count: it is missing in demo mode.
  const offlineSince = overview.error && overview.data ? overview.data.generated_at : null
  const live = useMemo(() => new Map((status.data?.sensors ?? []).map((s) => [s.id, s])), [status.data])
  const names = useMemo(
    () => Object.fromEntries((overview.data?.sensors ?? []).map((s) => [s.id, s.name])),
    [overview.data],
  )
  const weekly = useMemo(
    () => (report.data && now ? weeklyReport(report.data, localDay(now)) : null),
    [report.data, now],
  )
  const by = range === '1y' || range === 'all' ? 'month' : 'day'
  const periodDays = useMemo(() => {
    if (!daily.data) return []
    return daily.data.sensors.map((sensor) => ({ ...sensor, days: sensor.days.slice(-PERIOD_DAYS[range]) }))
  }, [daily.data, range])
  const targetRooms = periodDays
    .filter((s) => s.kind === 'ble' && s.target_temperature !== null)
    .map((sensor) => ({ sensor, periods: targetPeriods(sensor.days.filter(isRoomDay), by) }))
    .filter((room) => room.periods.length > 0)
  const outdoorDaily = periodDays.find((s) => s.kind === 'weather')
  // Only complete days: today's mean so far would overstate the cold morning.
  const today = now ? localDay(now) : ''
  const degreeDays = outdoorDaily
    ? degreeDayPeriods(outdoorDaily.days.filter(isOutdoorDay).filter((d) => d.day < today), by)
    : []
  const deltaMetric = metric === 'temperature' ? 'temperature' : 'absolute'
  const pi = status.data?.system

  return (
    <div className="mx-auto max-w-6xl px-4 pt-[max(1.5rem,env(safe-area-inset-top))] pb-10 sm:px-6">
      <header className="flex items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{t('title')}</h1>
        {overview.data && (
          <p className="text-sm text-muted">
            {t('updated')} {formatTime(overview.data.generated_at)}
          </p>
        )}
      </header>

      <StatusBanners banners={banners(status.data, offlineSince, now)} now={now} />

      {overview.error && !overview.data && (
        <p className="mt-6 rounded-2xl border border-border bg-surface p-5 text-ink-2">
          {t('loadError')}: {overview.error.message}
        </p>
      )}
      {!overview.data && !overview.error && <p className="mt-6 text-ink-2">{t('loading')}</p>}
      {overview.data && !hasData && (
        <p className="mt-6 rounded-2xl border border-border bg-surface p-5 text-ink-2">{t('noData')}</p>
      )}

      {hasData && (
        <>
          <section className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label={t('title')}>
            {sensors.map((sensor) => (
              <RoomCard
                key={sensor.id}
                sensor={sensor}
                outdoor={outdoor}
                live={offlineSince === null ? live.get(sensor.id) : undefined}
                color={colors[sensor.id] ?? theme.series[0]!}
                theme={theme}
                now={now}
              />
            ))}
          </section>

          {report.data && (
            <div className="mt-4">
              <WeeklyReport report={weekly} colors={colors} />
            </div>
          )}

          <div className="mt-4">
            <FilterBar range={range} metric={metric} onRange={setRange} onMetric={setMetric} />
          </div>

          <div className="mt-2 grid gap-4">
            {series.data && (
              <ChartCard
                title={`${t('history')} · ${t(metric)}`}
                hint={[
                  series.data.bucket === 300
                    ? t('historyHintRaw')
                    : t('historyHint', { bucket: t(`bucket_${series.data.bucket}` as MessageKey) }),
                  t('historyMarks'),
                ].join(' ')}
                table={historyTable(series.data, metric)}
              >
                <HistoryChart data={series.data} metric={metric} theme={theme} colors={colors} dimmed={series.loading} />
              </ChartCard>
            )}

            {series.data && mouldSensors(series.data).length > 0 && (
              <ChartCard title={t('mouldChart')} hint={t('mouldChartHint')} table={mouldTable(series.data)}>
                <MouldChart data={series.data} theme={theme} colors={colors} dimmed={series.loading} />
              </ChartCard>
            )}

            {series.data && outdoor && (
              <ChartCard
                title={`${t('delta')} · ${t(deltaMetric)}`}
                hint={deltaMetric === 'temperature' ? t('deltaHint') : t('deltaHintAbsolute')}
                table={deltaTable(series.data, deltaMetric)}
              >
                <DeltaChart data={series.data} metric={deltaMetric} theme={theme} colors={colors} dimmed={series.loading} />
              </ChartCard>
            )}

            {targetRooms.length > 0 && (
              <ChartCard
                title={t('targetChart')}
                hint={t('targetChartHint', { period: t(`period_${by}`) })}
                table={targetTable(targetRooms)}
              >
                <div className="grid gap-x-6 gap-y-2 lg:grid-cols-2">
                  {targetRooms.map(({ sensor, periods }) => (
                    <figure key={sensor.id} className="m-0">
                      <figcaption className="flex items-center gap-2 text-sm text-ink-2">
                        <span className="size-2.5 rounded-full" style={{ background: colors[sensor.id] }} aria-hidden />
                        {sensor.name} · {t('target', { value: formatValue(sensor.target_temperature, 'temperature') })}
                      </figcaption>
                      <TargetChart periods={periods} label={periodLabel} theme={theme} name={sensor.name} dimmed={daily.loading} />
                    </figure>
                  ))}
                </div>
              </ChartCard>
            )}

            {series.data && hasWeather(series.data) && (
              <ChartCard
                title={t('weather')}
                hint={t('weatherHint', { bucket: t(`bucket_${series.data.bucket}` as MessageKey) })}
                table={weatherTable(series.data)}
              >
                <WeatherChart
                  data={series.data}
                  theme={theme}
                  color={outdoor ? (colors[outdoor.id] ?? theme.series[0]!) : theme.series[0]!}
                  dimmed={series.loading}
                />
              </ChartCard>
            )}

            {degreeDays.length > 0 && outdoor && (
              <ChartCard
                title={t('degreeDays')}
                hint={t('degreeDaysHint', { total: formatNumber(degreeDays.reduce((sum, p) => sum + p.degrees, 0), 0) })}
                table={degreeDaysTable(degreeDays)}
              >
                <DegreeDaysChart
                  periods={degreeDays}
                  label={periodLabel}
                  color={colors[outdoor.id] ?? theme.series[0]!}
                  theme={theme}
                  dimmed={daily.loading}
                />
              </ChartCard>
            )}

            {profile.data && (
              <ChartCard
                title={`${t('profile')} · ${t(metric)}`}
                hint={t('profileHint', { days: profile.data.days })}
                table={profileTable(profile.data, metric)}
              >
                <ProfileChart data={profile.data} metric={metric} theme={theme} colors={colors} dimmed={profile.loading} />
              </ChartCard>
            )}

            {heatmap.data && (
              <ChartCard
                title={`${t('heatmap')} · ${t(metric)}`}
                hint={t('heatmapHint', { days: heatmap.data.days })}
                table={heatmapTable(heatmap.data, metric)}
              >
                <div className="grid gap-x-6 gap-y-2 lg:grid-cols-2">
                  {heatmap.data.sensors
                    .filter((s) => s.cells.length > 0)
                    .map((sensor) => (
                      <figure key={sensor.id} className="m-0">
                        <figcaption className="flex items-center gap-2 text-sm text-ink-2">
                          <span className="size-2.5 rounded-full" style={{ background: colors[sensor.id] }} aria-hidden />
                          {sensor.name}
                        </figcaption>
                        <HeatmapChart sensor={sensor} metric={metric} theme={theme} dimmed={heatmap.loading} />
                      </figure>
                    ))}
                </div>
              </ChartCard>
            )}
          </div>

          {(range === '1y' || range === 'all') && daily.data && (
            <div className="mt-4">
              <ChartCard
                title={`${t('calendar')} · ${t(metric)}`}
                hint={t('calendarHint')}
                table={calendarTable(daily.data.sensors, metric)}
              >
                <div className="grid gap-2">
                  {daily.data.sensors
                    .filter((s) => s.days.length > 0)
                    .map((sensor) => (
                      <figure key={sensor.id} className="m-0">
                        <figcaption className="flex items-center gap-2 text-sm text-ink-2">
                          <span className="size-2.5 rounded-full" style={{ background: colors[sensor.id] }} aria-hidden />
                          {sensor.name}
                        </figcaption>
                        <CalendarChart days={sensor.days} metric={metric} theme={theme} name={sensor.name} dimmed={daily.loading} />
                      </figure>
                    ))}
                </div>
              </ChartCard>
            </div>
          )}

          {events.data && (
            <div className="mt-4">
              <EventsCard events={events.data.events} names={names} />
            </div>
          )}

          {status.data && (
            <p className="mt-8 text-xs text-muted">
              {t('system', {
                mode: t(`mode_${status.data.bluetooth.scanning_mode}`),
                homekit: status.data.homekit.paired
                  ? t('homekitPaired', { n: status.data.homekit.controllers })
                  : t('homekitNotPaired'),
                pi:
                  pi && pi.cpu_temperature !== null
                    ? t('systemPi', {
                        temperature: formatValue(pi.cpu_temperature, 'temperature'),
                        power: pi.undervoltage_count ? t('power_issue', { n: pi.undervoltage_count }) : t('power_ok'),
                      })
                    : '',
                version: status.data.version,
              })}
            </p>
          )}

          <footer className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-muted">
            <a href="/api/export.csv" className="inline-flex items-center gap-1.5 text-ink-2 hover:text-ink" download>
              <DownloadIcon className="size-4" />
              {t('export')}
            </a>
            <span className="flex flex-wrap gap-x-3">
              {outdoor && (
                <a href="https://open-meteo.com" className="hover:text-ink" rel="noreferrer" target="_blank">
                  {t('weatherCredit')}
                </a>
              )}
              <a href="https://github.com/huulanka/mi-homekit-bridge" className="hover:text-ink" rel="noreferrer" target="_blank">
                mi-homekit-bridge
              </a>
            </span>
          </footer>
        </>
      )}
    </div>
  )
}

function historyTable(data: Series, metric: Metric) {
  const format = data.bucket === 'day' ? formatDate : formatDateTime
  return {
    columns: [t('time'), ...data.sensors.map((s) => `${s.name} (${t('avg')})`)],
    rows: () => {
      const byTs = new Map<number, (string | number)[]>()
      data.sensors.forEach((sensor, column) => {
        for (const point of sensor.points) {
          const row = byTs.get(point[0]) ?? Array<string>(data.sensors.length).fill('–')
          row[column] = formatValue(pick(point, metric)[1], metric)
          byTs.set(point[0], row)
        }
      })
      return [...byTs.entries()].sort((a, b) => b[0] - a[0]).map(([ts, row]) => [format(ts), ...row])
    },
  }
}

function mouldTable(data: Series) {
  const sensors = mouldSensors(data)
  const format = data.bucket === 'day' ? formatDate : formatDateTime
  return {
    columns: [t('time'), ...sensors.map((s) => s.name)],
    rows: () => {
      const byTs = new Map<number, string[]>()
      sensors.forEach((sensor, column) => {
        for (const [ts, value] of sensor.surface ?? []) {
          const row = byTs.get(ts) ?? Array<string>(sensors.length).fill('–')
          row[column] = formatValue(value, 'humidity')
          byTs.set(ts, row)
        }
      })
      return [...byTs.entries()].sort((a, b) => b[0] - a[0]).map(([ts, row]) => [format(ts), ...row])
    },
  }
}

function targetTable(rooms: { sensor: DailySensor; periods: ReturnType<typeof targetPeriods> }[]) {
  return {
    columns: [t('day'), ...rooms.flatMap(({ sensor }) => [`${sensor.name}: ${t('cold')}`, t('onTargetShort'), t('warm')])],
    rows: () => {
      const keys = [...new Set(rooms.flatMap((r) => r.periods.map((p) => p.key)))].sort().reverse()
      return keys.map((key) => [
        periodLabel(key),
        ...rooms.flatMap(({ periods }) => {
          const period = periods.find((p) => p.key === key)
          return period ? [formatPercent(period.cold), formatPercent(period.onTarget), formatPercent(period.warm)] : ['–', '–', '–']
        }),
      ])
    },
  }
}

function degreeDaysTable(periods: ReturnType<typeof degreeDayPeriods>) {
  return {
    columns: [t('day'), t('degreeDays'), t('temperature')],
    rows: () =>
      [...periods]
        .reverse()
        .map((p) => [periodLabel(p.key), formatNumber(p.degrees), formatValue(p.temperature, 'temperature')]),
  }
}

function weatherTable(data: Series) {
  const weather = data.sensors.find((s) => s.kind === 'weather')?.weather ?? []
  const format = data.bucket === 'day' ? formatDate : formatDateTime
  const number = (value: number | null, unit: string) => (value === null ? '–' : `${formatNumber(value)} ${unit}`)
  return {
    columns: [t('time'), t('sun'), t('wind'), t('rain')],
    rows: () =>
      [...weather]
        .reverse()
        .map(([ts, sun, wind, rain]) => [format(ts), number(sun, 'W/m²'), number(wind, 'km/h'), number(rain, 'mm')]),
  }
}

function calendarTable(sensors: DailySensor[], metric: Metric) {
  return {
    columns: [t('day'), ...sensors.map((s) => s.name)],
    rows: () => {
      const byDay = new Map<string, string[]>()
      sensors.forEach((sensor, column) => {
        for (const day of sensor.days) {
          const row = byDay.get(day.day) ?? Array<string>(sensors.length).fill('–')
          row[column] = formatValue(dayValue(day, metric), metric)
          byDay.set(day.day, row)
        }
      })
      return [...byDay.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([day, row]) => [periodLabel(day), ...row])
    },
  }
}

function deltaTable(data: Series, metric: Metric) {
  const deltas = computeDeltas(data, metric)
  const format = data.bucket === 'day' ? formatDate : formatDateTime
  return {
    columns: [t('time'), ...deltas.map((d) => d.name)],
    rows: () =>
      (deltas[0]?.points ?? [])
        .map((point, i) => [format(point[0] / 1000), ...deltas.map((d) => formatDelta(d.points[i]?.[1], metric))])
        .reverse(),
  }
}

function profileTable(data: Profile, metric: Metric) {
  const values = data.sensors.map((s) => profileValues(s.points, metric))
  return {
    columns: [t('hour'), ...data.sensors.map((s) => s.name)],
    rows: () => HOURS.map((hour) => [`${String(hour).padStart(2, '0')}:00`, ...values.map((v) => formatValue(v[hour], metric))]),
  }
}

function heatmapTable(data: Heatmap, metric: Metric) {
  return {
    columns: [t('day'), t('hour'), ...data.sensors.map((s) => s.name)],
    rows: () => {
      const byKey = new Map<string, (string | number)[]>()
      data.sensors.forEach((sensor, column) => {
        const { days, cells } = heatmapCells(sensor, metric)
        for (const [dayIndex, hour, value] of cells) {
          const key = `${days[dayIndex]} ${String(hour).padStart(2, '0')}`
          const row = byKey.get(key) ?? Array<string>(data.sensors.length).fill('–')
          row[column] = formatValue(value, metric)
          byKey.set(key, row)
        }
      })
      return [...byKey.entries()]
        .sort((a, b) => (a[0] < b[0] ? 1 : -1))
        .map(([key, row]) => [key.slice(0, 10), `${key.slice(11)}:00`, ...row])
    },
  }
}
