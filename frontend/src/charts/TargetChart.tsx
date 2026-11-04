import { useMemo } from 'react'
import { formatPercent } from '../format'
import { t } from '../i18n'
import type { Period } from '../report'
import type { Theme } from '../theme'
import { baseOption, tooltipTitle } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  periods: Period[]
  /** Label of a period key (day or month). */
  label: (key: string) => string
  theme: Theme
  name: string
  dimmed: boolean
}

/** Stacked 100 % bars per period: too cold (cool pole), on target (neutral gray),
 * too warm (warm pole). Text stays in ink colors; the legend names the colors. */
export function TargetChart({ periods, label, theme, name, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const base = baseOption(theme)
    const parts = [
      { id: 'cold', name: t('cold'), color: theme.cold, value: (p: Period) => p.cold },
      { id: 'on', name: t('onTargetShort'), color: theme.neutral, value: (p: Period) => p.onTarget },
      { id: 'warm', name: t('warm'), color: theme.warm, value: (p: Period) => p.warm },
    ]
    return {
      ...base,
      legend: { ...(base.legend as object), icon: 'roundRect', itemWidth: 10, itemHeight: 10, data: parts.map((p) => p.name) },
      grid: { ...(base.grid as object), top: 36 },
      tooltip: {
        ...(base.tooltip as object),
        axisPointer: { type: 'shadow', shadowStyle: { color: theme.gap } },
        formatter: (raw: unknown) => {
          const params = (Array.isArray(raw) ? raw : [raw]) as { dataIndex: number }[]
          const period = periods[params[0]?.dataIndex ?? -1]
          if (!period) return ''
          return (
            tooltipTitle(label(period.key)) +
            parts
              .map(
                (part) =>
                  `<div style="display:flex;align-items:center;gap:8px;margin-top:4px">` +
                  `<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${part.color}"></span>` +
                  `<strong style="font-variant-numeric:tabular-nums">${formatPercent(part.value(period))}</strong>` +
                  `<span style="opacity:.75">${part.name}</span></div>`,
              )
              .join('')
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
        min: 0,
        max: 1,
        interval: 0.5,
        axisLabel: { color: theme.muted, formatter: (v: number) => formatPercent(v) },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: parts.map((part, index) => ({
        id: part.id,
        name: part.name,
        type: 'bar',
        stack: 'share',
        barMaxWidth: 28,
        color: part.color,
        data: periods.map(part.value),
        itemStyle: {
          borderColor: theme.surface,
          borderWidth: 1,
          borderRadius: index === parts.length - 1 ? [4, 4, 0, 0] : 0,
        },
        emphasis: { disabled: true },
      })),
    }
  }, [periods, label, theme])
  return <EChart option={option} height={200} label={`${t('targetChart')}: ${name}`} dimmed={dimmed} />
}
