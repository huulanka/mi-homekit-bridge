import type { WeeklyReport as Report, RoomWeek } from '../report'
import { formatMinutes, formatNumber, formatPercent, formatShortDate, formatValue } from '../format'
import { t, type MessageKey } from '../i18n'

interface Row {
  key: MessageKey
  value: (week: RoomWeek) => number | null
  format: (value: number) => string
}

const ROWS: Row[] = [
  { key: 'report_temperature', value: (w) => w.temperature, format: (v) => formatValue(v, 'temperature') },
  { key: 'report_onTarget', value: (w) => w.onTarget, format: (v) => formatPercent(v) },
  { key: 'report_mould', value: (w) => w.mouldHours, format: (v) => t('hours', { n: Math.round(v) }) },
  { key: 'report_airings', value: (w) => w.airingsPerDay, format: (v) => formatNumber(v) },
  { key: 'report_recovery', value: (w) => w.recoveryMinutes, format: (v) => formatMinutes(v) },
  { key: 'report_absolute', value: (w) => w.absolute, format: (v) => formatValue(v, 'absolute') },
]

const date = (day: string) => formatShortDate(new Date(`${day}T12:00:00`))

export function WeeklyReport({ report, colors }: { report: Report | null; colors: Record<string, string> }) {
  const hasPrevious = report?.rooms.some((r) => r.previous) ?? false
  const rows = report ? ROWS.filter((row) => report.rooms.some((r) => row.value(r.current) !== null)) : []
  const outdoor = report?.outdoor
  return (
    <section className="rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="mb-3">
        <h2 className="text-base font-semibold text-ink">{t('report')}</h2>
        <p className="mt-0.5 text-sm text-ink-2">
          {report
            ? t(hasPrevious ? 'reportHint' : 'reportHintNoPrevious', { start: date(report.start), end: date(report.end) })
            : t('reportEmpty')}
        </p>
      </header>
      {report && report.rooms.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm tabular">
            <thead>
              <tr>
                <th scope="col" className="border-b border-border py-2 pr-4 font-medium text-ink-2">
                  {t('metricLabel')}
                </th>
                {report.rooms.map(({ sensor }) => (
                  <th key={sensor.id} scope="col" className="border-b border-border px-3 py-2 font-medium text-ink">
                    <span className="flex items-center gap-2">
                      <span className="size-2.5 rounded-full" style={{ background: colors[sensor.id] }} aria-hidden />
                      {sensor.name}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="align-top">
                  <th scope="row" className="border-b border-border py-2 pr-4 font-normal text-ink-2">
                    {t(row.key)}
                  </th>
                  {report.rooms.map(({ sensor, current, previous }) => {
                    const value = row.value(current)
                    const before = previous ? row.value(previous) : null
                    return (
                      <td key={sensor.id} className="border-b border-border px-3 py-2">
                        <span className="text-ink">{value === null ? '–' : row.format(value)}</span>
                        {before !== null && (
                          <span className="block text-xs text-muted">{t('reportPrevious', { value: row.format(before) })}</span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {outdoor && (
        <p className="mt-3 text-sm text-ink-2 tabular">
          {t('reportOutdoor', {
            temperature: formatValue(outdoor.current.temperature, 'temperature'),
            degrees: formatNumber(outdoor.current.heatingDegrees ?? 0, 0),
            rain: `${formatNumber(outdoor.current.precipitation ?? 0)} mm`,
          })}
          {outdoor.previous && outdoor.previous.heatingDegrees !== null && (
            <span className="text-muted">
              {' '}
              ({t('reportPrevious', { value: formatNumber(outdoor.previous.heatingDegrees, 0) })})
            </span>
          )}
        </p>
      )}
    </section>
  )
}
