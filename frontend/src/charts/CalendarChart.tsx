import { useMemo } from 'react'
import type { Metric, OutdoorDay, RoomDay } from '../api'
import { dayValue } from '../data'
import { escapeHtml, formatValue } from '../format'
import { locale, t } from '../i18n'
import type { Theme } from '../theme'
import { baseOption } from './common'
import { EChart } from './EChart'
import type { ChartOption } from './setup'

interface Props {
  days: (RoomDay | OutdoorDay)[]
  metric: Metric
  theme: Theme
  name: string
  dimmed: boolean
}

const longDate = new Intl.DateTimeFormat(locale, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })
const weekday = new Intl.DateTimeFormat(locale, { weekday: 'narrow' })
const month = new Intl.DateTimeFormat(locale, { month: 'short' })
// 2024-01-01 was a Monday.
const DAY_NAMES = Array.from({ length: 7 }, (_, i) => weekday.format(new Date(2023, 11, 31 + i)))
const MONTH_NAMES = Array.from({ length: 12 }, (_, i) => month.format(new Date(2024, i, 15)))

/** One square per day, like a contribution calendar, on the sensor's own scale. */
export function CalendarChart({ days, metric, theme, name, dimmed }: Props) {
  const option = useMemo((): ChartOption => {
    const cells = days
      .map((d) => [d.day, dayValue(d, metric)] as const)
      .filter((c): c is readonly [string, number] => c[1] !== null)
    const values = cells.map((c) => c[1])
    const min = values.length ? Math.floor(Math.min(...values)) : 0
    const max = values.length ? Math.ceil(Math.max(...values)) : 1
    const ramp = metric === 'temperature' ? theme.temperatureRamp : theme.humidityRamp
    const base = baseOption(theme)
    const first = days[0]?.day ?? ''
    const last = days[days.length - 1]?.day ?? first
    return {
      ...base,
      legend: undefined,
      tooltip: {
        ...(base.tooltip as object),
        trigger: 'item',
        formatter: (raw: unknown) => {
          const [day, value] = (raw as { value: [string, number] }).value
          return (
            `<strong style="font-variant-numeric:tabular-nums">${escapeHtml(formatValue(value, metric))}</strong>` +
            `<div style="font-size:12px;opacity:.7;margin-top:2px">${escapeHtml(longDate.format(new Date(`${day}T12:00:00`)))}</div>`
          )
        },
      },
      visualMap: {
        type: 'continuous',
        min,
        max,
        inRange: { color: [...ramp] },
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        itemWidth: 10,
        itemHeight: 160,
        text: [formatValue(max, metric), formatValue(min, metric)],
        textGap: 8,
        calculable: false,
        textStyle: { color: theme.muted, fontSize: 12 },
      },
      calendar: {
        range: [first, last],
        top: 24,
        left: 28,
        right: 8,
        bottom: 40,
        cellSize: ['auto', 13],
        splitLine: { show: false },
        itemStyle: { color: theme.gap, borderColor: theme.surface, borderWidth: 2 },
        yearLabel: { show: false },
        dayLabel: { firstDay: 1, nameMap: DAY_NAMES, color: theme.muted, fontSize: 10 },
        monthLabel: { nameMap: MONTH_NAMES, color: theme.muted, fontSize: 11 },
      },
      series: [
        {
          type: 'heatmap',
          coordinateSystem: 'calendar',
          name,
          data: cells.map((c) => [...c]),
          itemStyle: { borderColor: theme.surface, borderWidth: 2, borderRadius: 2 },
          emphasis: { itemStyle: { borderColor: theme.ink, borderWidth: 1 } },
        },
      ],
    }
  }, [days, metric, theme, name])
  return <EChart option={option} height={170} label={`${t('calendar')}: ${name}`} dimmed={dimmed} />
}
