import { useMemo } from 'react'
import { pick, type Metric, type Series } from '../api'
import { formatDate, formatDateTime } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { stepMs, withGaps } from '../data'
import { baseOption, fineScreen, formatValue, timeAxis, tooltipRow, tooltipTitle, valueAxis } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  data: Series
  metric: Metric
  theme: Theme
  colors: Record<string, string>
  dimmed: boolean
}

interface AxisParam {
  seriesId?: string
  value?: [number, number | null]
}

function buildHistoryOption(data: Series, metric: Metric, theme: Theme, colors: Record<string, string>): ChartOption {
  const step = stepMs(data.bucket)
  const aggregated = data.bucket !== 300
  const wide = window.innerWidth >= 640
  const ranges = new Map<string, Map<number, [number | null, number | null]>>()
  const series: NonNullable<ChartOption['series']> = []
  const names = new Map<string, string>()

  for (const sensor of data.sensors) {
    const color = colors[sensor.id] ?? theme.series[0]
    names.set(sensor.id, sensor.name)
    const values = sensor.points.map((p) => [p[0] * 1000, ...pick(p, metric)] as const)
    ranges.set(sensor.id, new Map(values.map(([ts, min, , max]) => [ts, [min, max]])))
    series.push({
      id: `avg:${sensor.id}`,
      name: sensor.name,
      type: 'line',
      color,
      data: withGaps(values.map(([ts, , avg]) => [ts, avg]), step),
      showSymbol: false,
      symbolSize: 8,
      lineStyle: { width: 2, cap: 'round', join: 'round' },
      emphasis: { disabled: true },
      endLabel: wide
        ? { show: true, formatter: '{a}', color: theme.ink2, fontSize: 12, distance: 6 }
        : { show: false },
      labelLayout: { hideOverlap: true },
      z: 3,
    })
    if (aggregated) {
      const band = `band:${sensor.id}`
      series.push(
        {
          id: `low:${sensor.id}`,
          name: sensor.name,
          type: 'line',
          color,
          stack: band,
          data: withGaps(values.map(([ts, min]) => [ts, min]), step),
          showSymbol: false,
          lineStyle: { opacity: 0 },
          tooltip: { show: false },
          silent: true,
          z: 1,
        },
        {
          id: `spread:${sensor.id}`,
          name: sensor.name,
          type: 'line',
          color,
          stack: band,
          data: withGaps(
            values.map(([ts, min, , max]) => [ts, min !== null && max !== null ? max - min : null]),
            step,
          ),
          showSymbol: false,
          lineStyle: { opacity: 0 },
          areaStyle: { color, opacity: 0.1 },
          tooltip: { show: false },
          silent: true,
          z: 1,
        },
      )
    }
  }

  const base = baseOption(theme)
  return {
    ...base,
    grid: { ...(base.grid as object), right: wide ? 96 : 8 },
    legend: { ...(base.legend as object), data: data.sensors.map((s) => s.name) },
    tooltip: {
      ...(base.tooltip as object),
      formatter: (raw: unknown) => {
        const params = (Array.isArray(raw) ? raw : [raw]) as AxisParam[]
        const rows = params.filter((p) => p.seriesId?.startsWith('avg:') && p.value && p.value[1] !== null)
        const ts = rows[0]?.value?.[0]
        if (ts === undefined) return ''
        const title = data.bucket === 'day' ? formatDate(ts / 1000) : formatDateTime(ts / 1000)
        return (
          tooltipTitle(title) +
          rows
            .map((p) => {
              const id = p.seriesId!.slice(4)
              const range = ranges.get(id)?.get(ts)
              const extra =
                aggregated && range && range[0] !== null && range[1] !== null
                  ? `${formatValue(range[0], metric)} – ${formatValue(range[1], metric)}`
                  : ''
              return tooltipRow(colors[id] ?? theme.ink, formatValue(p.value![1], metric), names.get(id) ?? id, extra)
            })
            .join('')
        )
      },
    },
    xAxis: timeAxis(theme),
    yAxis: valueAxis(theme, metric),
    dataZoom: fineScreen
      ? [{ type: 'inside', zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true, moveOnMouseWheel: false }]
      : [],
    series,
  }
}

export function HistoryChart({ data, metric, theme, colors, dimmed }: Props) {
  const option = useMemo(() => buildHistoryOption(data, metric, theme, colors), [data, metric, theme, colors])
  return <EChart option={option} height={320} label={`${t('history')}: ${t(metric)}`} dimmed={dimmed} />
}
