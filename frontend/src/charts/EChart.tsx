import { useEffect, useRef } from 'react'
import { echarts, type ChartOption } from './setup'

interface Props {
  option: ChartOption
  height: number
  /** Accessible summary; every chart also has a table view. */
  label: string
  /** Hold the previous render while new data loads. */
  dimmed?: boolean
}

export function EChart({ option, height, label, dimmed = false }: Props) {
  const element = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const el = element.current
    if (!el) return
    const instance = echarts.init(el, undefined, { renderer: 'svg' })
    chart.current = instance
    const observer = new ResizeObserver(() => instance.resize())
    observer.observe(el)
    return () => {
      observer.disconnect()
      instance.dispose()
      chart.current = null
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: true })
  }, [option])

  return (
    <div
      ref={element}
      role="img"
      aria-label={label}
      className="w-full transition-opacity duration-150"
      style={{ height, opacity: dimmed ? 0.55 : 1 }}
    />
  )
}
