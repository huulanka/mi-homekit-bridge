import { useMemo } from 'react'
import type { Metric, Series } from '../api'
import { computeDeltas, stepMs, withGaps } from '../data'
import { formatDate, formatDateTime, formatDelta } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption, fineScreen, timeAxis, tooltipRow, tooltipTitle, valueAxis } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  data: Series
  /** Relative humidity is not comparable between inside and outside. */
  metric: Exclude<Metric, 'humidity'>
  theme: Theme
  colors: Record<string, string>
  dimmed: boolean
}

export function DeltaChart({ data, metric, theme, colors, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const deltas = computeDeltas(data, metric)
    const step = stepMs(data.bucket)
    const names = new Map(deltas.map((d) => [d.id, d.name]))
    const base = baseOption(theme)
    const wide = window.innerWidth >= 640
    return {
      ...base,
      grid: { ...(base.grid as object), right: wide ? 96 : 8 },
      tooltip: {
        ...(base.tooltip as object),
        formatter: (raw: unknown) => {
          const params = (Array.isArray(raw) ? raw : [raw]) as { seriesId?: string; value?: [number, number | null] }[]
          const rows = params.filter((p) => p.value && p.value[1] !== null)
          const ts = rows[0]?.value?.[0]
          if (ts === undefined) return ''
          const title = data.bucket === 'day' ? formatDate(ts / 1000) : formatDateTime(ts / 1000)
          return (
            tooltipTitle(title) +
            rows
              .map((p) => tooltipRow(colors[p.seriesId!] ?? theme.ink, formatDelta(p.value![1], metric), names.get(p.seriesId!) ?? ''))
              .join('')
          )
        },
      },
      xAxis: timeAxis(theme),
      yAxis: {
        ...valueAxis(theme, 'delta'),
        axisLabel: { color: theme.muted, formatter: (v: number) => (metric === 'temperature' ? `${v} K` : `${v} g/m³`) },
      },
      dataZoom: fineScreen
        ? [{ type: 'inside', zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true, moveOnMouseWheel: false }]
        : [],
      series: deltas.map((delta, index) => ({
        id: delta.id,
        name: delta.name,
        type: 'line',
        color: colors[delta.id] ?? theme.series[0],
        data: withGaps(delta.points, step),
        showSymbol: false,
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        emphasis: { disabled: true },
        endLabel: wide ? { show: true, formatter: '{a}', color: theme.ink2, fontSize: 12, distance: 6 } : { show: false },
        labelLayout: { hideOverlap: true },
        markLine:
          index === 0
            ? {
                silent: true,
                symbol: 'none',
                label: { show: false },
                lineStyle: { color: theme.axis, width: 1, type: 'solid' },
                data: [{ yAxis: 0 }],
              }
            : undefined,
      })),
    }
  }, [data, metric, theme, colors])
  return <EChart option={option} height={260} label={t('delta')} dimmed={dimmed} />
}
