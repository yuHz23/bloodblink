import { useState, type FormEvent } from 'react'
import { Droplets, LogIn, AlertCircle } from 'lucide-react'
import { useAuth } from '../lib/auth'

/**
 * Màn đăng nhập BB-Console.
 *
 * Chỉ nhân viên cơ sở y tế và quản trị có tài khoản ở đây; người hiến dùng app
 * BB-SOS và nhận token ngay lúc đăng ký hồ sơ, không có mật khẩu.
 */
export default function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không đăng nhập được')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'var(--bb-gray-50)', padding: 24,
    }}>
      <div className="card" style={{ width: '100%', maxWidth: 400 }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Droplets size={36} color="var(--bb-red)" />
          <h1 style={{ fontSize: 22, fontWeight: 800, margin: '10px 0 2px' }}>BLOODBLINK</h1>
          <div style={{ fontSize: 13, color: 'var(--bb-gray-500)' }}>
            Cổng điều phối cho cơ sở y tế
          </div>
        </div>

        <form onSubmit={onSubmit}>
          <div className="form-group">
            <label htmlFor="username">Tên đăng nhập</label>
            <input
              id="username"
              value={username}
              autoComplete="username"
              onChange={e => setUsername(e.target.value)}
              placeholder="choray"
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Mật khẩu</label>
            <input
              id="password"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>

          {error && (
            <div style={{
              display: 'flex', gap: 8, alignItems: 'flex-start',
              background: '#fee2e2', color: '#b91c1c', borderRadius: 8,
              padding: '10px 12px', fontSize: 13, marginBottom: 12,
            }}>
              <AlertCircle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>{error}</span>
            </div>
          )}

          <button className="btn btn-primary" type="submit" disabled={busy}
                  style={{ width: '100%', justifyContent: 'center' }}>
            <LogIn size={16} /> {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </form>

        <p style={{ fontSize: 12, color: 'var(--bb-gray-400)', marginTop: 16, lineHeight: 1.6 }}>
          Người hiến máu không đăng nhập ở đây — dùng ứng dụng BB-SOS trên điện thoại.
        </p>
      </div>
    </div>
  )
}
