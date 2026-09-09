import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { COMPONENT_SHORT, SHELF_LIFE, formatHoursRemaining } from '../lib/constants'

export default function Inventory() {
  const [component, setComponent] = useState<string>('')
  const [withinHours, setWithinHours] = useState(168) // 7 days default

  // Chạy cả khi cửa sổ bị che — xem ghi chú ở Dashboard.tsx. Bảng này xếp theo
  // hạn dùng nên để cũ là nhìn nhầm đơn vị nào sắp hết hạn.
  const { data: units, isLoading } = useQuery({
    queryKey: ['expiring', withinHours, component],
    queryFn: () => api.listExpiring(withinHours, component || undefined),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  })

  return (
    <>
      <h2>Tồn kho FEFO</h2>
      <p className="subtitle">First Expired, First Out — chế phẩm sắp hết hạn được ưu tiên xuất trước</p>

      {/* Filters */}
      <div className="card" style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ margin: 0, minWidth: 160 }}>
          <label>Loại chế phẩm</label>
          <select value={component} onChange={e => setComponent(e.target.value)}>
            <option value="">Tất cả</option>
            <option value="RBC">Hồng cầu (RBC)</option>
            <option value="PLT">Tiểu cầu (PLT)</option>
            <option value="FFP">Huyết tương (FFP)</option>
          </select>
        </div>
        <div className="form-group" style={{ margin: 0, minWidth: 160 }}>
          <label>Xem hết hạn trong</label>
          <select value={withinHours} onChange={e => setWithinHours(Number(e.target.value))}>
            <option value={24}>24 giờ</option>
            <option value={48}>48 giờ</option>
            <option value={72}>72 giờ (3 ngày)</option>
            <option value={168}>7 ngày</option>
            <option value={336}>14 ngày</option>
            <option value={720}>30 ngày</option>
          </select>
        </div>
        <div style={{ fontSize: 13, color: 'var(--bb-gray-500)', marginLeft: 'auto' }}>
          {units ? `${units.length} đơn vị` : 'Đang tải...'}
        </div>
      </div>

      {/* FEFO Table */}
      {isLoading ? (
        <div className="card">Đang tải dữ liệu tồn kho...</div>
      ) : units && units.length > 0 ? (
        <div className="card" style={{ padding: 0 }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>DIN</th>
                  <th>Loại</th>
                  <th>Nhóm máu</th>
                  <th>Thể tích</th>
                  <th>Còn lại</th>
                  <th>Hạn dùng</th>
                  <th>Cơ sở</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {units.map((u, i) => (
                  <tr key={u.unit.id} style={{
                    background: u.urgency === 'expired' ? 'var(--bb-red-soft)' :
                                u.urgency === 'critical' ? 'var(--bb-red-soft)' :
                                u.urgency === 'warning' ? 'var(--bb-amber-soft)' : 'transparent'
                  }}>
                    <td style={{ color: 'var(--bb-gray-400)', fontSize: 12 }}>{i + 1}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{u.unit.isbt_din}</td>
                    <td><span style={{ fontWeight: 600 }}>{COMPONENT_SHORT[u.unit.component_code]}</span></td>
                    <td>{u.unit.abo}{u.unit.rh === '+' ? '⁺' : '⁻'}</td>
                    <td>{u.unit.volume_ml} ml</td>
                    <td style={{ fontWeight: 700, color:
                      u.urgency === 'expired' ? 'var(--bb-red)' :
                      u.urgency === 'critical' ? 'var(--bb-red)' :
                      u.urgency === 'warning' ? 'var(--bb-amber)' : 'var(--bb-gray-700)'
                    }}>
                      {formatHoursRemaining(u.hours_remaining)}
                    </td>
                    <td style={{ fontSize: 12 }}>
                      {SHELF_LIFE[u.unit.component_code]?.note || ''}
                    </td>
                    <td style={{ fontSize: 12 }}>{u.unit.held_by_facility_id.replace('fac-', '')}</td>
                    <td>
                      <span className={`badge badge-${u.urgency}`}>
                        {u.urgency === 'expired' ? 'Hết hạn' :
                         u.urgency === 'critical' ? 'Cấp bách' :
                         u.urgency === 'warning' ? 'Cảnh báo' : 'Bình thường'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: 'var(--bb-gray-500)' }}>
          Không có đơn vị nào hết hạn trong khoảng thời gian đã chọn.
        </div>
      )}

      {/* Legend */}
      <div className="card" style={{ fontSize: 12, color: 'var(--bb-gray-500)' }}>
        <strong>Chú thích:</strong> FEFO = First Expired, First Out (tiểu cầu hết hạn trước được xuất trước).{' '}
        Hạn dùng theo TT 26/2013/TT-BYT: Hồng cầu ≤42 ngày (2–6°C), Tiểu cầu ≤5 ngày (20–24°C, lắc liên tục),{' '}
        Huyết tương 12 tháng (−18…−25°C) / 24 tháng (≤−25°C).{' '}
        <strong>BB-Box phân biệt 2 chế độ nhiệt:</strong> bảo quản và vận chuyển (Điều 20).
      </div>
    </>
  )
}