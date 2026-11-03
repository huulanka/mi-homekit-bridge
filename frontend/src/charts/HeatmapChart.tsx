import { useMemo } from 'react'
import type { Heatmap, Metric } from '../api'
import { heatmapCells } from '../data'
import { escapeHtml, formatShortDate, formatValue } from '../format'
import { locale, t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

type Sensor = Heatmap['sensors'][number]

interface Props {
  sensor: Sensor
  metric: Metric
  theme: Theme
  dimmed: boolean
}

const longDate = new Intl.DateTimeFormat(locale, { weekday: 'short', day: 'numeric', month: 'long' })

export function HeatmapChart({ sensor, metric, theme, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const { days, cells, min, max } = heatmapCells(sensor, metric)
    const ramp = metric === 'temperature' ? theme.temperatureRamp : theme.humidityRamp
    const base = baseOption(theme)
    const dayLabel = (day: string) => formatShortDate(new Date(`${day}T12:00:00`))
    return {
      ...base,
      legend: undefined,
      grid: { left: 4, right: 4, top: 8, bottom: 44, containLabel: true },
      tooltip: {
        ...(base.tooltip as object),
        trigger: 'item',
        formatter: (raw: unknown) => {
          const param = raw as { value: [number, number, number] }
          const [dayIndex, hour, value] = param.value
          const day = days[dayIndex] ?? ''
          return (
            `<strong style="font-variant-numeric:tabular-nums">${escapeHtml(formatValue(value, metric))}</strong>` +
            `<div style="font-size:12px;opacity:.7;margin-top:2px">${escapeHtml(
              `${longDate.format(new Date(`${day}T12:00:00`))}, ${String(hour).padStart(2, '0')}:00`,
            )}</div>`
          )
        },
      },
      xAxis: {
        type: 'category',
        data: days,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, formatter: dayLabel, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'category',
        data: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
        inverse: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: theme.muted, interval: 5 },
      },
      visualMap: {
        type: 'continuous',
        min: Math.floor(min),
        max: Math.ceil(max),
        inRange: { color: [...ramp] },
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        itemWidth: 10,
        itemHeight: 180,
        text: [formatValue(Math.ceil(max), metric), formatValue(Math.floor(min), metric)],
        textGap: 8,
        calculable: false,
        textStyle: { color: theme.muted, fontSize: 12 },
        formatter: (value: unknown) => formatValue(Number(value), metric),
      },
      series: [
        {
          type: 'heatmap',
          name: sensor.name,
          data: cells.map((c) => [...c]),
          itemStyle: { borderColor: theme.surface, borderWidth: 1, borderRadius: 1 },
          emphasis: { itemStyle: { borderColor: theme.ink, borderWidth: 1 } },
          progressive: 0,
        },
      ],
    }
  }, [sensor, metric, theme])
  return <EChart option={option} height={300} label={`${t('heatmap')}: ${sensor.name}`} dimmed={dimmed} />
}
