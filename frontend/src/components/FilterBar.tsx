import type { Metric, RangeKey } from '../api'
import { t, type MessageKey } from '../i18n'

interface SegmentedProps<T extends string> {
  label: string
  value: T
  options: readonly T[]
  labelFor: (option: T) => string
  onChange: (value: T) => void
}

function Segmented<T extends string>({ label, value, options, labelFor, onChange }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="flex rounded-xl bg-wash p-1">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={option === value}
          onClick={() => onChange(option)}
          className={
            'rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors ' +
            (option === value
              ? 'bg-surface font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,0.08)]'
              : 'text-ink-2 hover:text-ink')
          }
        >
          {labelFor(option)}
        </button>
      ))}
    </div>
  )
}

export const RANGES = ['24h', '7d', '30d', '1y', 'all'] as const satisfies readonly RangeKey[]
const METRICS = ['temperature', 'humidity', 'absolute'] as const satisfies readonly Metric[]

interface Props {
  range: RangeKey
  metric: Metric
  onRange: (range: RangeKey) => void
  onMetric: (metric: Metric) => void
}

export function FilterBar({ range, metric, onRange, onMetric }: Props) {
  return (
    <div className="sticky top-0 z-10 -mx-4 bg-page/85 px-4 py-3 backdrop-blur-md sm:-mx-6 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-full overflow-x-auto">
          <Segmented
            label={t('range')}
            value={range}
            options={RANGES}
            labelFor={(r) => t(`range_${r}` as MessageKey)}
            onChange={onRange}
          />
        </div>
        <Segmented label={t('metric')} value={metric} options={METRICS} labelFor={(m) => t(m)} onChange={onMetric} />
      </div>
    </div>
  )
}
