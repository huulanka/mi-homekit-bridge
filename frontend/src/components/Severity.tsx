import type { Severity } from '../advice'
import { t } from '../i18n'
import { severityText } from '../severity'
import { AlertIcon, CheckIcon, WarningIcon } from './Icons'

interface SeverityIconProps {
  severity: Severity
  className?: string
  /** The text next to the icon already says it all: hide it from screen readers. */
  decorative?: boolean
}

/** Status icon in its reserved color. The meaning is always also given as text:
 * next to it (`decorative`) or as the accessible name. */
export function SeverityIcon({ severity, className = 'size-4', decorative = false }: SeverityIconProps) {
  const Icon = severity === 'good' ? CheckIcon : severity === 'warning' ? WarningIcon : AlertIcon
  const a11y = decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': t(`severity_${severity}`) }
  return (
    <span className={`inline-flex shrink-0 ${severityText[severity]}`} {...a11y}>
      <Icon className={className} />
    </span>
  )
}

