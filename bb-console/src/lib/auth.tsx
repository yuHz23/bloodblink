/**
 * BB-Console — Phiên đăng nhập.
 *
 * Token nằm trong localStorage; phiên hết hạn (401 từ bất kỳ lời gọi nào) sẽ
 * phát sự kiện `bb:auth-expired` và đưa người dùng về màn đăng nhập.
 */

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, getToken, setToken, clearToken, AUTH_EXPIRED_EVENT, type LoginResult } from './api'

export interface Session {
  role: string
  subject: string
  username: string | null
  fullName: string | null
  facilityId: string | null
  facilityName: string | null
}

interface AuthValue {
  session: Session | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isStaff: boolean
  isLocalBypass: boolean
}

const SESSION_KEY = 'bb_session'
const LOCAL_AUTH_BYPASS = import.meta.env.DEV && import.meta.env.VITE_LOCAL_AUTH_BYPASS === 'true'
const AuthContext = createContext<AuthValue | null>(null)

const LOCAL_SESSION: Session = {
  role: 'admin',
  subject: 'local-development',
  username: 'local',
  fullName: 'Chế độ phát triển local',
  facilityId: null,
  facilityName: 'Bỏ qua đăng nhập trên máy này',
}

function readStoredSession(): Session | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

function toSession(r: LoginResult): Session {
  return {
    role: r.role,
    subject: r.subject,
    username: r.username,
    fullName: r.full_name,
    facilityId: r.facility_id,
    facilityName: r.facility_name,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(LOCAL_AUTH_BYPASS ? LOCAL_SESSION : null)
  const [loading, setLoading] = useState(!LOCAL_AUTH_BYPASS)

  // Có token trong máy chưa chắc còn hiệu lực — hỏi lại /auth/me trước khi vào.
  useEffect(() => {
    if (LOCAL_AUTH_BYPASS) return
    const stored = readStoredSession()
    if (!getToken() || !stored) {
      setLoading(false)
      return
    }
    api.me()
      .then(() => setSession(stored))
      .catch(() => {
        clearToken()
        localStorage.removeItem(SESSION_KEY)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const onExpired = () => {
      if (LOCAL_AUTH_BYPASS) return
      localStorage.removeItem(SESSION_KEY)
      setSession(null)
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired)
  }, [])

  const login = async (username: string, password: string) => {
    const result = await api.login(username, password)
    setToken(result.access_token)
    const s = toSession(result)
    localStorage.setItem(SESSION_KEY, JSON.stringify(s))
    setSession(s)
  }

  const logout = () => {
    if (LOCAL_AUTH_BYPASS) return
    clearToken()
    localStorage.removeItem(SESSION_KEY)
    setSession(null)
  }

  const value: AuthValue = {
    session,
    loading,
    login,
    logout,
    isStaff: session?.role === 'facility_staff' || session?.role === 'admin',
    isLocalBypass: LOCAL_AUTH_BYPASS,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth phải nằm trong <AuthProvider>')
  return ctx
}
