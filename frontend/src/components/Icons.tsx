interface IconProps {
  className?: string
}

const common = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
}

export const DropIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M12 3.5c3.5 4.3 6 7.6 6 10.6a6 6 0 0 1-12 0c0-3 2.5-6.3 6-10.6Z" />
  </svg>
)

export const CloudIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M7 18h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 9.5 4.25 4.25 0 0 0 7 18Z" />
  </svg>
)

export const HomeIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1Z" />
  </svg>
)

export const WarningIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M12 4 2.8 19.5h18.4Z" />
    <path d="M12 10v4.5M12 17.2v.1" />
  </svg>
)

export function BatteryIcon({ level, className }: IconProps & { level: number }) {
  const width = Math.max(1, Math.round((Math.min(100, Math.max(0, level)) / 100) * 13))
  return (
    <svg viewBox="0 0 24 24" className={className} {...common}>
      <rect x="2.5" y="7.5" width="17" height="9" rx="2" />
      <path d="M21.5 10.5v3" />
      <rect x="4.5" y="9.5" width={width} height="5" rx="1" fill="currentColor" stroke="none" />
    </svg>
  )
}

export const DownloadIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19h14" />
  </svg>
)

export const CheckIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="m8.5 12.2 2.4 2.4 4.7-5" />
  </svg>
)

export const AlertIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5v5.5M12 16.2v.1" />
  </svg>
)

export const DotIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} aria-hidden>
    <circle cx="12" cy="12" r="3.5" fill="currentColor" />
  </svg>
)

/** Four bars of increasing height; `bars` of them are filled. */
export function SignalIcon({ bars, className }: IconProps & { bars: number }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <rect
          key={i}
          x={3.5 + i * 4.75}
          y={17 - (i + 1) * 3.25}
          width={3}
          height={(i + 1) * 3.25 + 2}
          rx={1}
          fill="currentColor"
          opacity={i < bars ? 1 : 0.25}
        />
      ))}
    </svg>
  )
}

export const ArrowUpIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M12 19V5.5M6.5 11 12 5.5 17.5 11" />
  </svg>
)

export const ArrowDownIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M12 5v13.5M6.5 13 12 18.5 17.5 13" />
  </svg>
)

/** A target: the room's desired temperature. */
export const TargetIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="4.5" />
    <circle cx="12" cy="12" r="0.6" fill="currentColor" />
  </svg>
)

export const SunIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <circle cx="12" cy="12" r="3.8" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
  </svg>
)

export const WindIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M3 9h11.5a2.5 2.5 0 1 0-2.5-2.5M3 13h15.5a2.5 2.5 0 1 1-2.5 2.5M3 17h7" />
  </svg>
)

export const RainIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="M7 15h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 6.5 4.25 4.25 0 0 0 7 15Z" />
    <path d="m9 18-1 2M13 18l-1 2M17 18l-1 2" />
  </svg>
)

/** An open window with air flowing in: airing. */
export const AirIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <rect x="3.5" y="4" width="11" height="16" rx="1.5" />
    <path d="M9 4v16M17 9.5h3.5M17 13h4.5M17 16.5h3" />
  </svg>
)

export const ChevronIcon = ({ className }: IconProps) => (
  <svg viewBox="0 0 24 24" className={className} {...common}>
    <path d="m8 10 4 4 4-4" />
  </svg>
)
