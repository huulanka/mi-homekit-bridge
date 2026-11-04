import { useMemo } from 'react'
import type { Series } from '../api'
import { mouldSensors, stepMs, withGaps } from '../data'
import { formatDate, formatDateTime } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption, fineScreen, formatValue, timeAxis, tooltipRow, tooltipTitle, valueAxis } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  data: Series
  theme: Theme
  colors: Record<string, string>
  dimmed: boolean
}

export function MouldChart({ data, theme, colors, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const step = stepMs(data.bucket)
    const sensors = mouldSensors(data)
    const names = new Map(sensors.map((s) => [s.id, s.name]))
    const values = sensors.flatMap((s) => (s.surface ?? []).map(([, v]) => v)).filter((v): v is number => v !== null)
    const low = Math.min(50, ...values)
    const base = baseOption(theme)
    const wide = window.innerWidth >= 640
    const reference = (value: number, label: string, color: string) => ({
      yAxis: value,
      lineStyle: { color, width: 1, type: 'dashed' as const },
      label: { show: true, position: 'insideEndTop' as const, formatter: label, color: theme.ink2, fontSize: 11 },
    })
    return {
      ...base,
      grid: { ...(base.grid as object), right: wide ? 96 : 8 },
      legend: { ...(base.legend as object), data: sensors.map((s) => s.name) },
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
              .map((p) => tooltipRow(colors[p.seriesId!] ?? theme.ink, formatValue(p.value![1], 'humidity'), names.get(p.seriesId!) ?? ''))
              .join('')
          )
        },
      },
      xAxis: timeAxis(theme),
      yAxis: { ...valueAxis(theme, 'humidity'), min: Math.floor(low / 10) * 10, max: 100 },
      dataZoom: fineScreen
        ? [{ type: 'inside', zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true, moveOnMouseWheel: false }]
        : [],
      series: sensors.map((sensor, index) => ({
        id: sensor.id,
        name: sensor.name,
        type: 'line',
        color: colors[sensor.id] ?? theme.series[0],
        data: withGaps(
          (sensor.surface ?? []).map(([ts, v]) => [ts * 1000, v]),
          step,
        ),
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
                data: [reference(70, t('cautionLine'), theme.axis), reference(80, t('mouldLine'), theme.ink2)],
              }
            : undefined,
      })),
    }
  }, [data, theme, colors])
  return <EChart option={option} height={260} label={t('mouldChart')} dimmed={dimmed} />
}
