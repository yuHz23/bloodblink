/**
 * BB-Console — Chọn chủ đề sáng/tối.
 *
 * Ba trạng thái: "sáng", "tối", và "theo hệ thống" (mặc định). Chọn sáng hay
 * tối sẽ đóng dấu `data-theme` lên <html>; chọn theo hệ thống thì gỡ dấu ra để
 * `prefers-color-scheme` trong index.css quyết định.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'bb_theme'

interface ThemeValue {
  theme: ThemeChoice
  setTheme: (t: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeValue | null>(null)

function readStored(): ThemeChoice {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system') return raw
  } catch {
    /* trình duyệt chặn lưu trữ — coi như theo hệ thống */
  }
  return 'system'
}

function apply(theme: ThemeChoice) {
  const root = document.documentElement
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(readStored)

  useEffect(() => { apply(theme) }, [theme])

  const setTheme = (next: ThemeChoice) => {
    setThemeState(next)
    try { localStorage.setItem(STORAGE_KEY, next) } catch { /* bỏ qua */ }
  }

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme phải nằm trong <ThemeProvider>')
  return ctx
}
