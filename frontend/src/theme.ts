export type Theme = 'light' | 'dark' | 'auto'

const KEY = 'or_theme'
const media = () => window.matchMedia('(prefers-color-scheme: dark)')

export const getTheme = (): Theme => (localStorage.getItem(KEY) as Theme) || 'auto'

export function applyTheme(t: Theme): void {
  localStorage.setItem(KEY, t)
  const dark = t === 'dark' || (t === 'auto' && media().matches)
  document.documentElement.classList.toggle('dark', dark)
}

/** Re-apply on system changes while in auto mode. Returns an unsubscribe fn. */
export function watchSystem(getCurrent: () => Theme): () => void {
  const m = media()
  const onChange = () => { if (getCurrent() === 'auto') applyTheme('auto') }
  m.addEventListener('change', onChange)
  return () => m.removeEventListener('change', onChange)
}
