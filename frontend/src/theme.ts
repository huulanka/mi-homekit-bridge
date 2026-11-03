import { useEffect, useState } from 'react'

/** Chart colors from the validated reference palette (see README / docs).
 * Categorical slots are assigned in fixed order by sensor, never cycled, and a
 * sensor keeps its slot whatever is filtered. Light and dark are selected steps. */
export interface Theme {
  mode: 'light' | 'dark'
  surface: string
  ink: string
  ink2: string
  muted: string
  grid: string
  axis: string
  series: readonly string[]
  /** Sequential ramps, low value first (on dark the low end recedes into the surface). */
  temperatureRamp: readonly string[]
  humidityRamp: readonly string[]
}

const BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']
const ORANGE = ['#fde6da', '#f9c4a8', '#f39e76', '#eb6834', '#c4511f', '#933a14', '#5f250c']

const LIGHT: Theme = {
  mode: 'light',
  surface: '#fcfcfb',
  ink: '#0b0b0b',
  ink2: '#52514e',
  muted: '#898781',
  grid: '#e1e0d9',
  axis: '#c3c2b7',
  series: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  temperatureRamp: ORANGE,
  humidityRamp: BLUE,
}

const DARK: Theme = {
  mode: 'dark',
  surface: '#1a1a19',
  ink: '#f0efec',
  ink2: '#c3c2b7',
  muted: '#898781',
  grid: '#2c2c2a',
  axis: '#383835',
  series: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  temperatureRamp: [...ORANGE].reverse(),
  humidityRamp: [...BLUE].reverse(),
}

const query = '(prefers-color-scheme: dark)'

export function useTheme(): Theme {
  const [dark, setDark] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const media = window.matchMedia(query)
    const onChange = (event: MediaQueryListEvent) => setDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return dark ? DARK : LIGHT
}

/** Slot for a sensor, by its position in the full sensor list. */
export function colorFor(theme: Theme, index: number): string {
  return theme.series[index % theme.series.length] ?? theme.series[0]!
}
