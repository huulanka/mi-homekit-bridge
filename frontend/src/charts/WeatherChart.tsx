import { useMemo } from 'react'
import type { Series } from '../api'
import { stepMs, withGaps } from '../data'
import { formatDate, formatDateTime, formatNumber } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption, timeAxis, tooltipTitle } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

type Kind = 'sun' | 'wind' | 'rain'

const UNIT: Record<Kind, string> = { sun: 'W/m²', wind: 'km/h', rain: 'mm' }
const COLUMN: Record<Kind, 1 | 2 | 3> = { sun: 1, wind: 2, rain: 3 }

interface Props {
  data: Series
  theme: Theme
  color: string
  dimmed: boolean
}

function Panel({ data, kind, theme, color, dimmed }: Props & { kind: Kind }) {
  const option = useMemo((): ChartOption => {
    const weather = data.sensors.find((s) => s.kind === 'weather')?.weather ?? []
    const step = stepMs(data.bucket)
    const values = weather.map((row) => [row[0] * 1000, row[COLUMN[kind]]] as [number, number | null])
    const base = baseOption(theme)
    const unit = UNIT[kind]
    return {
      ...base,
      legend: undefined,
      // A fixed label column keeps the three panels aligned on the time axis.
      grid: { left: 72, right: 8, top: 8, bottom: 24, containLabel: false },
      tooltip: {
        ...(base.tooltip as object),
        formatter: (raw: unknown) => {
          const params = (Array.isArray(raw) ? raw : [raw]) as { value?: [number, number | null] }[]
          const point = params[0]?.value
          if (!point || point[1] === null) return ''
          const title = data.bucket === 'day' ? formatDate(point[0] / 1000) : formatDateTime(point[0] / 1000)
          return tooltipTitle(title) + `<strong style="font-variant-numeric:tabular-nums">${formatNumber(point[1])} ${unit}</strong>`
        },
      },
      xAxis: { ...timeAxis(theme), min: data.start * 1000, max: data.end * 1000 },
      yAxis: {
        type: 'value',
        min: 0,
        splitNumber: 2,
        axisLabel: { color: theme.muted, formatter: (v: number) => `${v} ${unit}` },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        kind === 'rain'
          ? {
              type: 'bar',
              name: t(kind),
              color,
              barMaxWidth: 10,
              data: values,
              itemStyle: { borderRadius: [2, 2, 0, 0] },
              emphasis: { disabled: true },
            }
          : {
              type: 'line',
              name: t(kind),
              color,
              data: withGaps(values, step),
              showSymbol: false,
              lineStyle: { width: 2, cap: 'round', join: 'round' },
              areaStyle: kind === 'sun' ? { color, opacity: 0.12 } : undefined,
              emphasis: { disabled: true },
            },
      ],
    }
  }, [data, kind, theme, color])
  return <EChart option={option} height={110} label={`${t('weather')}: ${t(kind)}`} dimmed={dimmed} />
}

/** Small multiples with a shared time range: one measure per panel, no second axis. */
export function WeatherChart(props: Props) {
  return (
    <div className="grid gap-1">
      {(['sun', 'wind', 'rain'] as const).map((kind) => (
        <figure key={kind} className="m-0">
          <figcaption className="text-sm text-ink-2">{t(kind)}</figcaption>
          <Panel {...props} kind={kind} />
        </figure>
      ))}
    </div>
  )
}
