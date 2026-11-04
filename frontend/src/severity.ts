import type { Severity } from './advice'

/** Tailwind classes for the reserved status colors. */
export const severityText: Record<Severity, string> = {
  good: 'text-good',
  warning: 'text-warning',
  critical: 'text-critical',
}

export const severityFill: Record<Severity, string> = {
  good: 'bg-good',
  warning: 'bg-warning',
  critical: 'bg-critical',
}
