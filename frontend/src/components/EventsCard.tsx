import { useState } from 'react'
import type { BridgeEvent } from '../api'
import { describeEvent, eventSeverity } from '../events'
import { formatDateTime } from '../format'
import { t } from '../i18n'
import { DotIcon } from './Icons'
import { SeverityIcon } from './Severity'

const COLLAPSED = 6

export function EventsCard({ events, names }: { events: BridgeEvent[]; names: Record<string, string> }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? events : events.slice(0, COLLAPSED)
  return (
    <section className="rounded-2xl border border-border bg-surface p-5 shadow-[0_1px_2px_rgba(0,0,0,0.04)]">
      <header className="mb-3">
        <h2 className="text-base font-semibold text-ink">{t('events')}</h2>
        <p className="mt-0.5 text-sm text-ink-2">{t('eventsHint')}</p>
      </header>
      {events.length === 0 ? (
        <p className="text-sm text-muted">{t('eventsEmpty')}</p>
      ) : (
        <ol className="grid gap-2 text-sm">
          {shown.map((event, i) => {
            const severity = eventSeverity(event.kind)
            return (
              <li key={`${event.ts}-${i}`} className="flex items-start gap-2.5">
                {severity ? (
                  <SeverityIcon severity={severity} className="mt-0.5 size-4" />
                ) : (
                  <DotIcon className="mt-0.5 size-4 shrink-0 text-muted" />
                )}
                <span className="min-w-0 flex-1 text-ink">{describeEvent(event, names)}</span>
                <time className="shrink-0 text-xs text-muted tabular" dateTime={new Date(event.ts * 1000).toISOString()}>
                  {formatDateTime(event.ts)}
                </time>
              </li>
            )
          })}
        </ol>
      )}
      {events.length > COLLAPSED && (
        <button
          type="button"
          className="mt-3 text-sm text-ink-2 hover:text-ink"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? t('showLess') : t('showAll', { n: events.length })}
        </button>
      )}
    </section>
  )
}
