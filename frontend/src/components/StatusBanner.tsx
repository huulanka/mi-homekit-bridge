import type { Banner } from '../advice'
import { formatDateTime, formatTime } from '../format'
import { t } from '../i18n'
import { SeverityIcon } from './Severity'

function message(banner: Banner, now: number): string {
  // Within the last 20 hours the time alone is clear; older needs the day.
  const time = banner.since === null ? '' : now - banner.since < 20 * 3600 ? formatTime(banner.since) : formatDateTime(banner.since)
  if (banner.kind === 'offline') return t('offline', { time })
  if (banner.kind === 'homekit') return t('homekitUnpaired')
  return t(banner.severity === 'critical' ? 'bluetooth_failed' : 'bluetooth_recovering', { time })
}

export function StatusBanners({ banners, now }: { banners: Banner[]; now: number }) {
  if (banners.length === 0) return null
  return (
    <div className="mt-4 grid gap-2" role="status" aria-live="polite">
      {banners.map((banner) => (
        <p
          key={banner.kind}
          className="flex items-start gap-2.5 rounded-2xl border border-border bg-surface px-4 py-3 text-sm text-ink"
        >
          <SeverityIcon severity={banner.severity} className="mt-px size-5" />
          <span>{message(banner, now)}</span>
        </p>
      ))}
    </div>
  )
}
