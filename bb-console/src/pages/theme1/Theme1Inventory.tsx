import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarClock, Droplets, Filter, Warehouse } from 'lucide-react'
import { api } from '../../lib/api'
import { COMPONENT_SHORT, formatHoursRemaining } from '../../lib/constants'

const BLOOD_COLORS = ['#ce272e', '#d99a24', '#2874a6', '#24a889', '#9d76c5', '#6d819a', '#b76548', '#4d9c79']

export default function Theme1Inventory() {
  const [component, setComponent] = useState('')
  const [withinHours, setWithinHours] = useState(720)
  const summary = useQuery({ queryKey: ['theme1-inventory-summary'], queryFn: api.inventorySummary, refetchInterval: 30_000 })
  const facilities = useQuery({ queryKey: ['theme1-facilities'], queryFn: api.listFacilities })
  const expiring = useQuery({ queryKey: ['theme1-expiring', component, withinHours], queryFn: () => api.listExpiring(withinHours, component || undefined, undefined, 50), refetchInterval: 30_000, refetchIntervalInBackground: true })

  const groups = useMemo(() => {
    const grouped = new Map<string, number>()
    for (const item of summary.data?.by_blood_type ?? []) grouped.set(`${item.abo}${item.rh}`, (grouped.get(`${item.abo}${item.rh}`) ?? 0) + item.count)
    return [...grouped.entries()].sort((a, b) => b[1] - a[1])
  }, [summary.data?.by_blood_type])
  const maxBloodCount = Math.max(1, ...groups.map(([, count]) => count))
  const availableComponents = (summary.data?.by_component_status ?? []).filter(item => item.status === 'available')
  const componentTotal = availableComponents.reduce((total, item) => total + item.count, 0)
  let gradientEnd = 0
  const componentGradient = availableComponents.map((item, index) => {
    const start = gradientEnd
    gradientEnd += componentTotal ? item.count / componentTotal * 100 : 0
    return `${BLOOD_COLORS[index % BLOOD_COLORS.length]} ${start.toFixed(1)}% ${gradientEnd.toFixed(1)}%`
  }).join(', ')
  const facilityName = (id: string) => facilities.data?.find(facility => facility.id === id)?.name ?? id

  return <>
    <div className="theme1-page-heading"><div><span className="theme1-eyebrow"><Warehouse size={13} /> Quản lý chế phẩm</span><h2>Tồn kho FEFO</h2><p>Ưu tiên sử dụng đơn vị máu sắp hết hạn trước, theo dõi tồn kho toàn mạng lưới.</p></div><span className="theme1-status-pill"><i /> Cập nhật mỗi 30 giây</span></div>

    <section className="theme1-kpis theme1-inventory-kpis" aria-label="Tóm tắt tồn kho">
      <article className="theme1-kpi theme1-kpi-green"><span className="theme1-kpi-icon"><Droplets size={21} /></span><div><span className="theme1-kpi-label">Tổng đơn vị sẵn sàng</span><strong>{summary.data?.total_available.toLocaleString('vi-VN') ?? '—'}</strong><small>Đơn vị còn hạn</small></div></article>
      <article className="theme1-kpi theme1-kpi-red"><span className="theme1-kpi-icon"><Droplets size={21} /></span><div><span className="theme1-kpi-label">Nhóm máu ít nhất</span><strong>{groups.length ? groups.at(-1)?.[0] : '—'}</strong><small>{groups.length ? `${groups.at(-1)?.[1]} đơn vị ghi nhận` : 'Theo tồn kho hiện tại'}</small></div></article>
      <article className="theme1-kpi theme1-kpi-gold"><span className="theme1-kpi-icon"><CalendarClock size={21} /></span><div><span className="theme1-kpi-label">Sắp hết hạn trong 3 ngày</span><strong>{summary.data?.expiring_within_72h ?? '—'}</strong><small>Cần ưu tiên xuất trước</small></div></article>
    </section>

    <section className="theme1-panel theme1-filter-panel" aria-label="Bộ lọc tồn kho">
      <div className="theme1-filter-heading"><Filter size={16} /><strong>Lọc dữ liệu</strong></div>
      <label>Chế phẩm<select value={component} onChange={event => setComponent(event.target.value)}><option value="">Tất cả chế phẩm</option><option value="RBC">Khối hồng cầu</option><option value="PLT">Khối tiểu cầu</option><option value="FFP">Huyết tương</option></select></label>
      <label>Khoảng thời gian<select value={withinHours} onChange={event => setWithinHours(Number(event.target.value))}><option value={72}>3 ngày</option><option value={168}>7 ngày</option><option value={336}>14 ngày</option><option value={720}>30 ngày</option></select></label>
    </section>

    <div className="theme1-inventory-charts">
      <section className="theme1-panel theme1-blood-chart"><div className="theme1-panel-title"><h3>Tồn kho theo nhóm máu</h3><span className="theme1-chart-legend"><i /> Số đơn vị ghi nhận</span></div>
        {summary.isLoading ? <div className="theme1-empty">Đang tải tồn kho…</div> : groups.length ? <div className="theme1-bars" aria-label="Biểu đồ tồn kho theo nhóm máu">
          {groups.map(([bloodType, count], index) => <div className="theme1-bar-column" key={bloodType}><strong>{count.toLocaleString('vi-VN')}</strong><i><b style={{ height: `${Math.max(8, count / maxBloodCount * 100)}%`, background: BLOOD_COLORS[index % BLOOD_COLORS.length] }} /></i><span>{bloodType}</span></div>)}
        </div> : <div className="theme1-empty">Chưa có số liệu theo nhóm máu.</div>}
      </section>
      <section className="theme1-panel theme1-component-chart"><div className="theme1-panel-title"><h3>Tồn kho theo chế phẩm</h3></div>
        <div className="theme1-donut-layout"><div className="theme1-donut" style={{ background: componentTotal ? `conic-gradient(${componentGradient})` : '#e7e4dc' }}><span><strong>{componentTotal.toLocaleString('vi-VN')}</strong><small>đơn vị<br />sẵn sàng</small></span></div>
          <div className="theme1-donut-legend">{availableComponents.map((item, index) => <div key={item.component}><i style={{ background: BLOOD_COLORS[index % BLOOD_COLORS.length] }} /><span>{COMPONENT_SHORT[item.component] ?? item.component}</span><strong>{item.count.toLocaleString('vi-VN')}</strong></div>)}</div>
        </div>
      </section>
    </div>

    <section className="theme1-panel theme1-stock-table"><div className="theme1-panel-title"><h3>Đơn vị máu sắp hết hạn</h3><span className="theme1-table-count">{expiring.data?.length ?? 0} kết quả</span></div>
      {expiring.isLoading ? <div className="theme1-empty" role="status">Đang tải danh sách tồn kho…</div> : expiring.data?.length ? <div className="table-wrap"><table><thead><tr><th>Nhóm máu</th><th>Chế phẩm</th><th>Cơ sở</th><th>Thể tích</th><th>Thời gian còn lại</th><th>Hạn sử dụng</th><th>Trạng thái</th></tr></thead><tbody>
        {expiring.data.map(({ unit, hours_remaining: hoursRemaining, urgency }) => <tr key={unit.id}><td><span className={`theme1-blood-badge${urgency === 'critical' || urgency === 'expired' ? ' is-low' : ''}`}>{unit.abo}{unit.rh}</span></td><td>{COMPONENT_SHORT[unit.component_code] ?? unit.component_code}</td><td>{facilityName(unit.held_by_facility_id)}</td><td>{unit.volume_ml} ml</td><td className={urgency === 'critical' || urgency === 'expired' ? 'theme1-expiry-critical' : ''}>{formatHoursRemaining(hoursRemaining)}</td><td>{new Date(unit.expires_at).toLocaleDateString('vi-VN')}</td><td><span className={`theme1-expiry-tag ${urgency}`}>{urgency === 'expired' ? 'Đã hết hạn' : urgency === 'critical' ? '≤ 3 ngày' : urgency === 'warning' ? '≤ 7 ngày' : 'Còn hạn'}</span></td></tr>)}
      </tbody></table></div> : <div className="theme1-empty">Không có đơn vị máu sắp hết hạn trong khoảng thời gian đã chọn.</div>}
    </section>
  </>
}
