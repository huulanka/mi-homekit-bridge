import { useMemo, useState } from 'react'
import { pick, type Heatmap, type Metric, type Overview, type Profile, type RangeKey, type Series } from './api'
import { DeltaChart } from './charts/DeltaChart'
import { HeatmapChart } from './charts/HeatmapChart'
import { HistoryChart } from './charts/HistoryChart'
import { ProfileChart } from './charts/ProfileChart'
import { ChartCard } from './components/ChartCard'
import { FilterBar, RANGES } from './components/FilterBar'
import { DownloadIcon } from './components/Icons'
import { RoomCard } from './components/RoomCard'
import { HOURS, computeDeltas, heatmapCells, profileValues } from './data'
import { formatDate, formatDateTime, formatDelta, formatTime, formatValue } from './format'
import { t, type MessageKey } from './i18n'
import { colorFor, useTheme } from './theme'
import { useApi } from './useApi'

const PROFILE_DAYS: Record<RangeKey, number> = { '24h': 7, '7d': 7, '30d': 30, '1y': 365, all: 365 }
const HEATMAP_DAYS: Record<RangeKey, number> = { '24h': 14, '7d': 14, '30d': 30, '1y': 90, all: 90 }

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
  const [metric, setMetric] = usePersisted<Metric>('metric', ['temperature', 'humidity'], 'temperature')

  const overview = useApi<Overview>('/api/overview', 60_000)
  const series = useApi<Series>(`/api/series?range=${range}`, 300_000)
  const profile = useApi<Profile>(`/api/profile?days=${PROFILE_DAYS[range]}`, 900_000)
  const heatmap = useApi<Heatmap>(`/api/heatmap?days=${HEATMAP_DAYS[range]}`, 900_000)

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
                color={colors[sensor.id] ?? theme.series[0]!}
                theme={theme}
                now={now}
              />
            ))}
          </section>

          <div className="mt-4">
            <FilterBar range={range} metric={metric} onRange={setRange} onMetric={setMetric} />
          </div>

          <div className="mt-2 grid gap-4">
            {series.data && (
              <ChartCard
                title={`${t('history')} · ${t(metric)}`}
                hint={
                  series.data.bucket === 300
                    ? t('historyHintRaw')
                    : t('historyHint', { bucket: t(`bucket_${series.data.bucket}` as MessageKey) })
                }
                table={historyTable(series.data, metric)}
              >
                <HistoryChart data={series.data} metric={metric} theme={theme} colors={colors} dimmed={series.loading} />
              </ChartCard>
            )}

            {series.data && outdoor && (
              <ChartCard
                title={`${t('delta')} · ${t(metric)}`}
                hint={t('deltaHint')}
                table={deltaTable(series.data, metric)}
              >
                <DeltaChart data={series.data} metric={metric} theme={theme} colors={colors} dimmed={series.loading} />
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

          <footer className="mt-8 flex flex-wrap items-center justify-between gap-3 text-sm text-muted">
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
