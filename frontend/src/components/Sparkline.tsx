interface Props {
  values: (number | null)[]
  color: string
  surface: string
  label: string
}

/** Last 24 hours in the sensor's color; gaps stay gaps. */
export function Sparkline({ values, color, surface, label }: Props) {
  const width = 240
  const height = 40
  const pad = 5
  const numbers = values.filter((v): v is number => v !== null)
  if (numbers.length < 2) return <div className="h-10" aria-hidden />
  const min = Math.min(...numbers)
  const max = Math.max(...numbers)
  const span = max - min || 1
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - 2 * pad)
  const y = (v: number) => height - pad - ((v - min) / span) * (height - 2 * pad)

  let path = ''
  let pen = false
  values.forEach((v, i) => {
    if (v === null) {
      pen = false
      return
    }
    path += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
    pen = true
  })
  const lastIndex = values.findLastIndex((v) => v !== null)
  const last = values[lastIndex] ?? null

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-10 w-full" preserveAspectRatio="none" role="img" aria-label={label}>
      <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {last !== null && (
        <circle cx={x(lastIndex)} cy={y(last)} r={4} fill={color} stroke={surface} strokeWidth={2} vectorEffect="non-scaling-stroke" />
      )}
    </svg>
  )
}
