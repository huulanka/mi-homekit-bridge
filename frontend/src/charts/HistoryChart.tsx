import { useMemo } from 'react'
import { pick, type Metric, type Series } from '../api'
import { formatDate, formatDateTime, formatKelvin, formatMinutes } from '../format'
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
  axisValue?: number
  value?: [number, number | null]
}

/** The point of a series closest to `ts` (ms) with a value. */
function nearest(values: readonly (readonly [number, number | null])[], ts: number): [number, number] | null {
  let best: [number, number] | null = null
  for (const [x, y] of values) {
    if (y === null) continue
    if (!best || Math.abs(x - ts) < Math.abs(best[0] - ts)) best = [x, y]
  }
  return best
}

function buildHistoryOption(data: Series, metric: Metric, theme: Theme, colors: Record<string, string>): ChartOption {
  const step = stepMs(data.bucket)
  const aggregated = data.bucket !== 300
  const wide = window.innerWidth >= 640
  const ranges = new Map<string, Map<number, [number | null, number | null]>>()
  const series: NonNullable<ChartOption['series']> = []
  const names = new Map<string, string>()
  const targets = metric === 'temperature' ? data.sensors.map((s) => s.target_temperature).filter((v): v is number => v !== null) : []
  const gaps = data.gaps ?? []
  const airings = data.airings ?? []

  for (const [index, sensor] of data.sensors.entries()) {
    const color = colors[sensor.id] ?? theme.series[0]
    names.set(sensor.id, sensor.name)
    const values = sensor.points.map((p) => [p[0] * 1000, ...pick(p, metric)] as const)
    ranges.set(sensor.id, new Map(values.map(([ts, min, , max]) => [ts, [min, max]])))
    const averages = values.map(([ts, , avg]) => [ts, avg] as const)
    const marks = airings
      .filter((a) => a.sensor_id === sensor.id)
      .map((a) => nearest(averages, a.lowest * 1000))
      .filter((m): m is [number, number] => m !== null)
    const target = metric === 'temperature' ? sensor.target_temperature : null
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
      markLine:
        target !== null
          ? {
              silent: true,
              symbol: 'none',
              label: { show: false },
              lineStyle: { color, width: 1.5, type: 'dashed' },
              data: [{ yAxis: target }],
            }
          : undefined,
      markPoint: marks.length
        ? {
            silent: true,
            symbol: 'circle',
            symbolSize: 9,
            label: { show: false },
            itemStyle: { color, borderColor: theme.surface, borderWidth: 2 },
            data: marks.map((coord) => ({ name: 'airing', coord })),
          }
        : undefined,
      markArea:
        index === 0 && gaps.length
          ? {
              silent: true,
              itemStyle: { color: theme.gap },
              data: gaps.map(([start, end]) => [{ xAxis: start * 1000 }, { xAxis: end * 1000 }]),
            }
          : undefined,
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
        const ts = rows[0]?.value?.[0] ?? params[0]?.axisValue
        if (ts === undefined) return ''
        const title = data.bucket === 'day' ? formatDate(ts / 1000) : formatDateTime(ts / 1000)
        const gap = gaps.find(([start, end]) => ts / 1000 >= start && ts / 1000 <= end)
        const notes = airings
          .filter((a) => a.lowest * 1000 >= ts && a.lowest * 1000 < ts + step)
          .map((a) =>
            tooltipRow(
              colors[a.sensor_id] ?? theme.ink,
              t('airedTooltip', {
                drop: formatKelvin(a.drop),
                recovery:
                  a.recovery_minutes === null
                    ? t('notRecovered')
                    : t('recoveredAfter', { duration: formatMinutes(a.recovery_minutes) }),
              }),
              names.get(a.sensor_id) ?? '',
            ),
          )
        if (rows.length === 0 && !gap) return ''
        return (
          tooltipTitle(title) +
          (gap ? tooltipTitle(t(`gap_${gap[2]}`)) : '') +
          notes.join('') +
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
    yAxis: {
      ...valueAxis(theme, metric),
      // Keep the dashed target lines in view.
      ...(targets.length
        ? {
            min: (extent: { min: number }) => Math.floor(Math.min(extent.min, Math.min(...targets) - 0.5)),
            max: (extent: { max: number }) => Math.ceil(Math.max(extent.max, Math.max(...targets) + 0.5)),
          }
        : {}),
    },
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
