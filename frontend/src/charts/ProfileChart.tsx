import { useMemo } from 'react'
import type { Metric, Profile } from '../api'
import { HOURS, profileValues } from '../data'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption, formatValue, tooltipRow, tooltipTitle, valueAxis } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  data: Profile
  metric: Metric
  theme: Theme
  colors: Record<string, string>
  dimmed: boolean
}

const hourLabel = (hour: number) => `${String(hour).padStart(2, '0')}:00`

export function ProfileChart({ data, metric, theme, colors, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const base = baseOption(theme)
    const wide = window.innerWidth >= 640
    const names = new Map(data.sensors.map((s) => [s.id, s.name]))
    return {
      ...base,
      grid: { ...(base.grid as object), right: wide ? 96 : 8 },
      tooltip: {
        ...(base.tooltip as object),
        formatter: (raw: unknown) => {
          const params = (Array.isArray(raw) ? raw : [raw]) as { seriesId?: string; dataIndex: number; value?: number | null }[]
          const first = params[0]
          if (!first) return ''
          return (
            tooltipTitle(hourLabel(first.dataIndex)) +
            params
              .filter((p) => p.value !== null && p.value !== undefined)
              .map((p) => tooltipRow(colors[p.seriesId!] ?? theme.ink, formatValue(p.value!, metric), names.get(p.seriesId!) ?? ''))
              .join('')
          )
        },
      },
      xAxis: {
        type: 'category',
        data: HOURS.map((h) => String(h).padStart(2, '0')),
        boundaryGap: false,
        axisLine: { lineStyle: { color: theme.axis } },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, interval: 2 },
      },
      yAxis: valueAxis(theme, metric),
      series: data.sensors.map((sensor) => ({
        id: sensor.id,
        name: sensor.name,
        type: 'line',
        color: colors[sensor.id] ?? theme.series[0],
        data: profileValues(sensor.points, metric),
        showSymbol: false,
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        emphasis: { disabled: true },
        endLabel: wide ? { show: true, formatter: '{a}', color: theme.ink2, fontSize: 12, distance: 6 } : { show: false },
        labelLayout: { hideOverlap: true },
      })),
    }
  }, [data, metric, theme, colors])
  return <EChart option={option} height={260} label={t('profile')} dimmed={dimmed} />
}
