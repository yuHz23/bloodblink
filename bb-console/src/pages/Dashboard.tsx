import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { COMPONENT_SHORT, formatHoursRemaining } from '../lib/constants'
import { AlertTriangle, X } from 'lucide-react'

export default function Dashboard() {
  const [detailHours, setDetailHours] = useState<number | null>(null)
  // `refetchIntervalInBackground` bật ở mọi truy vấn có nhịp trong console này.
  //
  // React Query mặc định DỪNG `refetchInterval` khi `document.hidden`, mà cửa sổ
  // bị che là trạng thái bình thường của phòng trực: người ta mở bệnh án, gọi
  // điện, alt-tab. Quay lại thấy số liệu của lúc rời đi mà không có dấu hiệu gì
  // là nó đã cũ — nguy hiểm hơn nhiều so với chi phí một lượt gọi mỗi 30 giây.
  const { data: summary, isLoading } = useQuery({
    queryKey: ['inventory-summary'],
    queryFn: () => api.inventorySummary(),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  })

  const { data: expiring } = useQuery({
    queryKey: ['expiring-24h'],
    queryFn: () => api.listExpiring(24),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  })

  const {
    data: detailUnits,
    isLoading: detailLoading,
    error: detailError,
  } = useQuery({
    queryKey: ['expiring-detail', detailHours],
    queryFn: () => api.listExpiring(detailHours ?? 24, undefined, undefined, 200),
    enabled: detailHours !== null,
  })

  if (isLoading || !summary) return <div>Đang tải...</div>

  const criticalUnits = (expiring || []).filter(u => u.urgency === 'critical' || u.urgency === 'expired')

  return (
    <>
      <h2>Tổng quan cụm máu</h2>
      <p className="subtitle">Theo dõi tồn kho FEFO theo thời gian thực — TT 26/2013/TT-BYT</p>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-number" style={{ color: 'var(--bb-gray-900)' }}>
            {summary.total_available}
          </div>
          <div className="stat-label">Tổng đơn vị khả dụng</div>
        </div>
        <button className="stat-card stat-card-action" type="button" onClick={() => setDetailHours(72)}>
          <div className="stat-number" style={{ color: 'var(--bb-amber)' }}>
            {summary.expiring_within_72h}
          </div>
          <div className="stat-label">Hết hạn trong 72 giờ</div>
        </button>
        <button className="stat-card stat-card-action" type="button" onClick={() => setDetailHours(24)}>
          <div className="stat-number" style={{ color: 'var(--bb-red)' }}>
            {summary.expiring_within_24h}
          </div>
          <div className="stat-label">Hết hạn trong 24 giờ</div>
        </button>
        <div className="stat-card">
          <div className="stat-number" style={{ color: criticalUnits.length > 0 ? 'var(--bb-red)' : 'var(--bb-green)' }}>
            {criticalUnits.length}
          </div>
          <div className="stat-label">Tiểu cầu sắp hết hạn</div>
        </div>
      </div>

      {/* Component breakdown */}
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Tồn kho theo chế phẩm</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
          {['RBC', 'PLT', 'FFP'].map(comp => {
            const available = summary.by_component_status
              .filter(r => r.component === comp && r.status === 'available')
              .reduce((sum, r) => sum + r.count, 0)
            const total = summary.by_component_status
              .filter(r => r.component === comp)
              .reduce((sum, r) => sum + r.count, 0)
            return (
              <div key={comp} style={{
                background: 'var(--bb-gray-50)', borderRadius: 8, padding: '12px 14px',
              }}>
                <div style={{ fontSize: 11, color: 'var(--bb-gray-500)', textTransform: 'uppercase', letterSpacing: 0.06, fontWeight: 600 }}>
                  {COMPONENT_SHORT[comp]}
                </div>
                <div style={{ fontSize: 24, fontWeight: 700, marginTop: 2 }}>
                  {available}
                  <span style={{ fontSize: 13, color: 'var(--bb-gray-400)', fontWeight: 400 }}> / {total}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--bb-gray-500)' }}>khả dụng / tổng</div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Blood type matrix */}
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Phân bố nhóm máu khả dụng</h3>
        <div className="table-wrap">
          <table className="blood-type-matrix">
            <thead>
              <tr>
                <th>Nhóm máu</th>
                <th>O⁺</th><th>O⁻</th>
                <th>A⁺</th><th>A⁻</th>
                <th>B⁺</th><th>B⁻</th>
                <th>AB⁺</th><th>AB⁻</th>
                <th>Tổng</th>
              </tr>
            </thead>
            <tbody>
              {/*
                `/inventory/summary` gộp theo nhóm máu, KHÔNG tách theo chế phẩm.
                Bản trước vẽ ba dòng RBC/PLT/FFP nhưng lọc bằng `r.component === comp || true`
                nên cả ba dòng ra cùng một con số — nhìn như số liệu theo chế phẩm mà không phải.
                Trả về đúng một dòng tổng cho tới khi có endpoint tách theo chế phẩm.
              */}
              {[null].map(() => (
                <tr key="all">
                  <td style={{ fontWeight: 600 }}>Tất cả chế phẩm</td>
                  {['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-'].map(type => {
                    const abo = type.startsWith('AB') ? 'AB' : type[0]
                    const rh = type.includes('-') ? '-' : '+'
                    const count = summary.by_blood_type
                      .filter(r => r.abo === abo && r.rh === rh)
                      .reduce((sum, r) => sum + r.count, 0)
                    return <td key={type} style={{ textAlign: 'center', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{count || '—'}</td>
                  })}
                  <td style={{ fontWeight: 600, textAlign: 'center' }}>
                    {summary.by_blood_type.reduce((sum, r) => sum + r.count, 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 8 }}>
          Phân bố người Việt: O~45%, B~30%, A~20%, AB~5% · Rh(D)⁻: ~0,1% (Viện HH–TMTW)
        </p>
      </div>

      {/* Critical alert */}
      {criticalUnits.length > 0 && (
        <div className="card" style={{ borderLeft: '3px solid var(--bb-red)' }}>
          <h3 style={{ color: 'var(--bb-red)', marginBottom: 8 }}>
            <AlertTriangle size={16} style={{ display: 'inline', verticalAlign: -2 }} /> Cảnh báo: Tiểu cầu sắp hết hạn
          </h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>DIN</th><th>Nhóm</th><th>Còn lại</th><th>Cơ sở</th><th>Trạng thái</th></tr>
              </thead>
              <tbody>
                {criticalUnits.slice(0, 5).map(u => (
                  <tr key={u.unit.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {u.unit.isbt_din.startsWith('MOCK-FEFO-') && <span className="badge badge-routine">Mô phỏng </span>}
                      {u.unit.isbt_din}
                    </td>
                    <td><span className={`badge badge-${u.urgency}`}>{u.unit.abo}{u.unit.rh}</span></td>
                    <td>{formatHoursRemaining(u.hours_remaining)}</td>
                    <td style={{ fontSize: 12 }}>{u.unit.held_by_facility_id}</td>
                    <td><span className={`badge badge-${u.urgency}`}>
                      {u.urgency === 'expired' ? 'Hết hạn' : u.urgency === 'critical' ? 'Cần luân chuyển' : 'Cảnh báo'}
                    </span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Facility breakdown */}
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Tồn kho theo cơ sở</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Cơ sở</th><th>Hồng cầu</th><th>Tiểu cầu</th><th>Huyết tương</th></tr>
            </thead>
            <tbody>
              {Array.from(new Set(summary.by_facility_component.map(r => r.facility_id))).map(fid => (
                <tr key={fid}>
                  <td style={{ fontWeight: 500 }}>{fid.replace('fac-', '').replace(/-/g, ' ').toUpperCase()}</td>
                  {['RBC', 'PLT', 'FFP'].map(comp => {
                    const count = summary.by_facility_component
                      .filter(r => r.facility_id === fid && r.component === comp)
                      .reduce((sum, r) => sum + r.count, 0)
                    return <td key={comp} style={{ textAlign: 'center' }}>{count || '—'}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {detailHours !== null && (
        <div className="detail-modal-backdrop" role="presentation" onMouseDown={event => {
          if (event.target === event.currentTarget) setDetailHours(null)
        }}>
          <section className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="expiring-title">
            <div className="detail-modal-head">
              <div>
                <h3 id="expiring-title">Đơn vị sắp hết hạn trong {detailHours} giờ</h3>
                <p>{detailUnits?.length ?? 0} đơn vị · sắp xếp theo hạn dùng gần nhất</p>
              </div>
              <button className="btn btn-secondary detail-modal-close" type="button"
                aria-label="Đóng chi tiết" onClick={() => setDetailHours(null)}>
                <X size={16} />
              </button>
            </div>
            {detailLoading ? (
              <div className="detail-modal-empty">Đang tải danh sách…</div>
            ) : detailError ? (
              <div className="detail-modal-empty" role="alert">Không tải được danh sách đơn vị sắp hết hạn.</div>
            ) : detailUnits && detailUnits.length > 0 ? (
              <div className="table-wrap detail-modal-table">
                <table>
                  <thead><tr><th>DIN</th><th>Nhóm máu</th><th>Chế phẩm</th><th>Còn lại</th><th>Cơ sở</th><th>Hạn dùng</th></tr></thead>
                  <tbody>
                    {detailUnits.map(({ unit, hours_remaining, urgency }) => (
                      <tr key={unit.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                          {unit.isbt_din.startsWith('MOCK-FEFO-') && <span className="badge badge-routine">Mô phỏng </span>}
                          {unit.isbt_din}
                        </td>
                        <td><span className={`badge badge-${urgency}`}>{unit.abo}{unit.rh}</span></td>
                        <td>{COMPONENT_SHORT[unit.component_code] ?? unit.component_code}</td>
                        <td style={{ fontWeight: 700 }}>{formatHoursRemaining(hours_remaining)}</td>
                        <td>{unit.held_by_facility_id.replace('fac-', '').replace(/-/g, ' ')}</td>
                        <td>{new Date(unit.expires_at).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="detail-modal-empty">Không có đơn vị nào trong khoảng thời gian này.</div>
            )}
          </section>
        </div>
      )}
    </>
  )
}
