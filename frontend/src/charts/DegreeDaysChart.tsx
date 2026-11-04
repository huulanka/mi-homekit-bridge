import { useMemo } from 'react'
import { formatNumber, formatValue } from '../format'
import { t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption, tooltipTitle } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  periods: { key: string; degrees: number; temperature: number | null }[]
  label: (key: string) => string
  color: string
  theme: Theme
  dimmed: boolean
}

export function DegreeDaysChart({ periods, label, color, theme, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const base = baseOption(theme)
    return {
      ...base,
      legend: undefined,
      grid: { ...(base.grid as object), top: 12 },
      tooltip: {
        ...(base.tooltip as object),
        axisPointer: { type: 'shadow', shadowStyle: { color: theme.gap } },
        formatter: (raw: unknown) => {
          const params = (Array.isArray(raw) ? raw : [raw]) as { dataIndex: number }[]
          const period = periods[params[0]?.dataIndex ?? -1]
          if (!period) return ''
          return (
            tooltipTitle(label(period.key)) +
            `<div style="margin-top:4px"><strong style="font-variant-numeric:tabular-nums">${t('degreeDaysValue', {
              value: formatNumber(period.degrees),
            })}</strong></div>` +
            (period.temperature === null
              ? ''
              : `<div style="opacity:.75">${t('outdoorMean', { value: formatValue(period.temperature, 'temperature') })}</div>`)
          )
        },
      },
      xAxis: {
        type: 'category',
        data: periods.map((p) => label(p.key)),
        axisLine: { lineStyle: { color: theme.axis } },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        splitNumber: 3,
        axisLabel: { color: theme.muted },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          type: 'bar',
          name: t('degreeDays'),
          color,
          barMaxWidth: 28,
          data: periods.map((p) => Math.round(p.degrees * 10) / 10),
          itemStyle: { borderRadius: [4, 4, 0, 0] },
          emphasis: { disabled: true },
        },
      ],
    }
  }, [periods, label, color, theme])
  return <EChart option={option} height={200} label={t('degreeDays')} dimmed={dimmed} />
}
