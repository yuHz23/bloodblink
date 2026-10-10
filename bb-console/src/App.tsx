import { Routes, Route, NavLink } from 'react-router-dom'
import { Droplets, FileText, BarChart3, Map, Siren, LogOut, Sun, Moon, Monitor } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Inventory from './pages/Inventory'
import Matching from './pages/Matching'
import SOS from './pages/SOS'
import Routing from './pages/Routing'
import Donors from './pages/Donors'
import MapView from './pages/MapView'
import Reports from './pages/Reports'
import Login from './pages/Login'
import { useAuth } from './lib/auth'
import { useTheme, type ThemeChoice } from './lib/theme'

const THEMES: { key: ThemeChoice; icon: typeof Sun; label: string }[] = [
  { key: 'light', icon: Sun, label: 'Sáng' },
  { key: 'system', icon: Monitor, label: 'Theo hệ thống' },
  { key: 'dark', icon: Moon, label: 'Tối' },
]

export default function App() {
  const { session, loading, logout, isLocalBypass } = useAuth()
  const { theme, setTheme } = useTheme()

  // Đang hỏi lại /auth/me xem token còn hiệu lực không.
  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center',
                    color: 'var(--bb-gray-500)' }}>
        Đang kiểm tra phiên đăng nhập…
      </div>
    )
  }

  if (!session) return <Login />

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-brand-row">
            <Droplets size={23} strokeWidth={2.4} aria-hidden="true" />
            <h1>BLOOD-BLINK <em>SOS</em></h1>
            <span className="brand-flag" role="img" aria-label="Cờ Việt Nam">★</span>
          </div>
          <span>Kết nối những trái tim Việt</span>
        </div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
            <BarChart3 size={18} /> Tổng quan
          </NavLink>
          <NavLink to="/inventory" className={({ isActive }) => isActive ? 'active' : ''}>
            <Droplets size={18} /> Tồn kho FEFO
          </NavLink>
          <NavLink to="/map" className={({ isActive }) => isActive ? 'active' : ''}>
            <Map size={18} /> Bản đồ
          </NavLink>
          <NavLink to="/sos" className={({ isActive }) => isActive ? 'active' : ''}>
            <Siren size={18} /> SOS &amp; các vòng
          </NavLink>
          {/* Nhật ký cho biết cơ sở nào tra ai lúc nào nên backend chỉ cho vai
              trò admin; ẩn mục này với tài khoản cơ sở thay vì để họ bấm vào rồi
              nhận 403. */}
          {session.role === 'admin' && (
            <NavLink to="/reports" className={({ isActive }) => isActive ? 'active' : ''}>
              <FileText size={18} /> Nhật ký
            </NavLink>
          )}
        </nav>

        <div className="sidebar-bottom">
          <div className="theme-toggle" style={{ marginBottom: 14 }}>
            {THEMES.map(({ key, icon: Icon, label }) => (
              <button
                key={key}
                className={theme === key ? 'active' : ''}
                onClick={() => setTheme(key)}
                title={label}
                aria-label={label}
                aria-pressed={theme === key}
              >
                <Icon size={15} />
              </button>
            ))}
          </div>

          <div className="sidebar-user-name">
            {isLocalBypass ? 'Chế độ local' : session.fullName ?? session.username}
          </div>
          <div className="sidebar-user-detail">
            {isLocalBypass ? 'Đã bỏ qua đăng nhập trên máy này' : session.facilityName ?? (session.role === 'admin' ? 'Quản trị hệ thống' : 'Nhân viên cơ sở')}
          </div>
          {!isLocalBypass && (
            <button className="btn btn-secondary" onClick={logout} style={{ width: '100%', justifyContent: 'center' }}>
              <LogOut size={14} /> Đăng xuất
            </button>
          )}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/matching" element={<Matching />} />
          <Route path="/donors" element={<Donors />} />
          <Route path="/sos" element={<SOS />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/routing" element={<Routing />} />
          <Route path="/reports" element={<Reports />} />
          {/* Đường dẫn lạ về Tổng quan, thay vì render khung trống. */}
          <Route path="*" element={<Dashboard />} />
        </Routes>
      </main>
    </div>
  )
}
