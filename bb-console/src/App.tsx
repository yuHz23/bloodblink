import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, Bell, Building2, ChevronDown, ChevronRight, CircleUserRound, Clock3, Droplets, FileText, BarChart3, Map, MapPinned, Siren, LogOut, Sun, Moon, Monitor } from 'lucide-react'
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
import { api } from './lib/api'
import Theme1Overview from './pages/theme1/Theme1Overview'
import Theme1Map from './pages/theme1/Theme1Map'
import Theme1Inventory from './pages/theme1/Theme1Inventory'
import Theme1Inbox from './pages/theme1/Theme1Inbox'

const THEMES: { key: ThemeChoice; icon: typeof Sun; label: string }[] = [
  { key: 'light', icon: Sun, label: 'Sáng' },
  { key: 'system', icon: Monitor, label: 'Theo hệ thống' },
  { key: 'dark', icon: Moon, label: 'Tối' },
]

export default function App() {
  const { session, loading, logout, isLocalBypass } = useAuth()
  const { theme, setTheme } = useTheme()
  const { pathname } = useLocation()
  const theme1Mode = import.meta.env.MODE === 'theme1'
  const shellHealth = useQuery({ queryKey: ['theme1-shell-health'], queryFn: api.health, enabled: theme1Mode, refetchInterval: 15_000 })
  const theme1PageTitle = ({
    '/': 'Tổng quan điều phối',
    '/map': 'Điều phối SOS',
    '/inventory': 'Tồn kho FEFO',
    '/inbox': 'Hộp thư bệnh viện',
    '/sos': 'SOS & các vòng',
    '/matching': 'Ghép nguồn',
    '/routing': 'Định tuyến',
    '/reports': 'Nhật ký hoạt động',
    '/donors': 'Người hiến máu',
  } as Record<string, string>)[pathname] ?? 'Tổng quan điều phối'

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
    <div className={`app${theme1Mode ? ' app-theme1' : ''}`}>
      <aside className="sidebar">
        <div className="logo">
          <div className="logo-brand-row">
            <Droplets size={23} strokeWidth={2.4} aria-hidden="true" />
            <h1>BLOOD-BLINK <em>SOS</em></h1>
            <span className="brand-flag" role="img" aria-label="Cờ Việt Nam">★</span>
          </div>
          <span>Kết nối những trái tim Việt</span>
        </div>
        <nav aria-label="Điều hướng chính">
          {theme1Mode ? <>
            <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
              <BarChart3 size={18} /> Tổng quan
            </NavLink>
            <NavLink to="/map" className={({ isActive }) => isActive ? 'active' : ''}>
              <MapPinned size={18} /> Bản đồ SOS
            </NavLink>
            <NavLink to="/inventory" className={({ isActive }) => isActive ? 'active' : ''}>
              <Droplets size={18} /> Tồn kho FEFO
            </NavLink>
            <NavLink to="/inbox" className={({ isActive }) => isActive ? 'active' : ''}>
              <Building2 size={18} /> Hộp thư bệnh viện
            </NavLink>
            <NavLink to="/sos" className={({ isActive }) => isActive ? 'active' : ''}>
              <Siren size={18} /> SOS &amp; các vòng
            </NavLink>
            <NavLink to="/matching" className={({ isActive }) => isActive ? 'active' : ''}>
              <ArrowLeftRight size={18} /> Điều phối
            </NavLink>
            <NavLink to="/routing" className={({ isActive }) => isActive ? 'active' : ''}>
              <Map size={18} /> Định tuyến
            </NavLink>
            {session.role === 'admin' && <NavLink to="/reports" className={({ isActive }) => isActive ? 'active' : ''}>
              <FileText size={18} /> Nhật ký
            </NavLink>}
          </> : <>
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
          </>}
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
      <section className="app-workspace">
        {theme1Mode && <header className="theme1-topbar">
          <div className="theme1-breadcrumb" aria-label="Vị trí hiện tại">
            <span>BLOOD-BLINK SOS</span><ChevronRight size={15} aria-hidden="true" /><strong>{theme1PageTitle}</strong>
          </div>
          <div className="theme1-topbar-actions">
            <span className={`theme1-system-state${shellHealth.data?.status === 'ok' ? '' : ' is-offline'}`}><i />{shellHealth.data?.status === 'ok' ? 'Hệ thống hoạt động' : shellHealth.isLoading ? 'Đang kết nối' : 'Kết nối gián đoạn'}</span>
            <span className="theme1-topbar-divider" />
            <span className="theme1-clock"><Clock3 size={16} /><span>{new Date().toLocaleDateString('vi-VN')}<strong>{new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</strong></span></span>
            <button className="theme1-bell" aria-label="Thông báo" type="button"><Bell size={18} /><i /></button>
            <span className="theme1-topbar-divider" />
            <div className="theme1-account"><CircleUserRound size={28} /><span><strong>{isLocalBypass ? 'Điều phối viên' : session.fullName ?? session.username}</strong><small>{session.role === 'admin' ? 'Trung tâm điều phối' : session.facilityName ?? 'Nhân viên cơ sở'}</small></span><ChevronDown size={15} /></div>
          </div>
        </header>}
        <main className="main">
        <Routes>
          <Route path="/" element={theme1Mode ? <Theme1Overview /> : <Dashboard />} />
          <Route path="/inventory" element={theme1Mode ? <Theme1Inventory /> : <Inventory />} />
          <Route path="/matching" element={<Matching />} />
          <Route path="/donors" element={<Donors />} />
          <Route path="/sos" element={<SOS />} />
          <Route path="/map" element={theme1Mode ? <Theme1Map /> : <MapView />} />
          <Route path="/routing" element={<Routing />} />
          <Route path="/reports" element={<Reports />} />
          {theme1Mode && <Route path="/inbox" element={<Theme1Inbox />} />}
          {/* Đường dẫn lạ về Tổng quan, thay vì render khung trống. */}
          <Route path="*" element={<Dashboard />} />
        </Routes>
        </main>
      </section>
    </div>
  )
}
