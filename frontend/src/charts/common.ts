import type { Metric } from '../api'
import { escapeHtml, formatValue } from '../format'
import type { Theme } from '../theme'
import type { ChartOption } from './setup'

export const fineScreen = window.matchMedia('(pointer: fine)').matches

export function baseOption(theme: Theme): ChartOption {
  return {
    animation: false,
    textStyle: { fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: theme.ink2 },
    grid: { left: 4, right: 4, top: 40, bottom: 4, containLabel: true },
    legend: {
      top: 0,
      left: 0,
      // A short, thin key that mirrors the 2px line marks.
      icon: 'roundRect',
      itemWidth: 14,
      itemHeight: 3,
      itemStyle: { borderWidth: 0 },
      textStyle: { color: theme.ink2, fontSize: 13 },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: theme.surface,
      borderColor: theme.mode === 'dark' ? 'rgba(255,255,255,0.12)' : 'rgba(11,11,11,0.12)',
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: theme.ink, fontSize: 13 },
      extraCssText: 'border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,0.12);',
      axisPointer: { type: 'line', lineStyle: { color: theme.axis, width: 1 } },
    },
  }
}

export function valueAxis(theme: Theme, metric: Metric | 'delta') {
  const suffix = metric === 'temperature' ? ' °C' : metric === 'humidity' ? ' %' : metric === 'absolute' ? ' g/m³' : ''
  return {
    type: 'value' as const,
    scale: true,
    splitNumber: 4,
    axisLabel: { color: theme.muted, formatter: (v: number) => `${v}${suffix}` },
    splitLine: { lineStyle: { color: theme.grid, width: 1, type: 'solid' as const } },
    axisLine: { show: false },
    axisTick: { show: false },
  }
}

export function timeAxis(theme: Theme) {
  return {
    type: 'time' as const,
    axisLine: { lineStyle: { color: theme.axis } },
    axisTick: { show: false },
    axisLabel: { color: theme.muted, hideOverlap: true },
    splitLine: { show: false },
  }
}

/** One tooltip row: line key in the series color, value first (strong), name after. */
export function tooltipRow(color: string, value: string, name: string, extra = ''): string {
  return (
    `<div style="display:flex;align-items:center;gap:8px;margin-top:4px">` +
    `<span style="display:inline-block;width:12px;height:2px;border-radius:1px;background:${color}"></span>` +
    `<strong style="font-variant-numeric:tabular-nums">${escapeHtml(value)}</strong>` +
    `<span style="opacity:.75">${escapeHtml(name)}</span>` +
    (extra ? `<span style="opacity:.6;font-size:12px">${escapeHtml(extra)}</span>` : '') +
    `</div>`
  )
}

export function tooltipTitle(text: string): string {
  return `<div style="font-size:12px;opacity:.7">${escapeHtml(text)}</div>`
}

export { formatValue }
