/**
 * Theme mode: black-on-white or white-on-black.
 *
 * Semi Design scopes its dark tokens to `body[theme-mode=dark]`, so switching
 * modes is a single attribute flip — no re-render of the component tree needed.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemeMode = 'light' | 'dark'

const THEME_KEY = 'ftui.theme'

interface ThemeContextValue {
  mode: ThemeMode
  toggle: () => void
  setMode: (mode: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readMode(): ThemeMode {
  const stored = localStorage.getItem(THEME_KEY)
  return stored === 'light' || stored === 'dark' ? stored : 'dark'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readMode)

  useEffect(() => {
    document.body.setAttribute('theme-mode', mode)
    // The root element carries the attribute too, so `color-scheme` can key off it
    // and the browser paints its own scrollbars to match. Without this the dark
    // theme keeps light scrollbars, which is glaring under wide tables.
    document.documentElement.setAttribute('theme-mode', mode)
    localStorage.setItem(THEME_KEY, mode)
  }, [mode])

  const setMode = useCallback((next: ThemeMode) => setModeState(next), [])
  const toggle = useCallback(
    () => setModeState((prev) => (prev === 'dark' ? 'light' : 'dark')),
    [],
  )

  const value = useMemo(() => ({ mode, toggle, setMode }), [mode, toggle, setMode])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
