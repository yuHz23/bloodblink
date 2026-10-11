import { useQuery } from '@tanstack/react-query'
import { Activity, ArrowRight, Building2, Clock3, Droplets, Siren } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type SosEvent } from '../../lib/api'
import { COMPONENT_SHORT } from '../../lib/constants'

function eventBloodType(event: SosEvent) {
  return event.abo ? `${event.abo}${event.rh ?? ''}` : 'Chưa rõ nhóm máu'
}

function eventTime(value: string) {
  return new Date(value).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
}

export default function Theme1Overview() {
  const summary = useQuery({ queryKey: ['theme1-inventory-summary'], queryFn: api.inventorySummary, refetchInterval: 30_000 })
  const facilities = useQuery({ queryKey: ['theme1-facilities'], queryFn: api.listFacilities, refetchInterval: 60_000 })
  const activeEvents = useQuery({ queryKey: ['theme1-open-sos'], queryFn: api.listOpenSosEvents, refetchInterval: 5_000, refetchIntervalInBackground: true })
  const recentEvents = useQuery({ queryKey: ['theme1-recent-sos'], queryFn: api.listSosEvents, refetchInterval: 30_000, refetchIntervalInBackground: true })
  const health = useQuery({ queryKey: ['theme1-health'], queryFn: api.health, refetchInterval: 15_000 })

  const latestEvents = [...(recentEvents.data ?? [])].sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at)).slice(0, 4)
  const facilityName = (id: string | null) => facilities.data?.find(facility => facility.id === id)?.name ?? 'Cơ sở trong mạng lưới'
  const connected = health.data?.status === 'ok'
  const metricValues = [
    { label: 'Ca SOS đang mở', value: activeEvents.data?.length ?? '—', icon: Siren, color: 'red', note: 'Cần theo dõi ngay' },
    { label: 'Đơn vị máu sẵn sàng', value: summary.data?.total_available.toLocaleString('vi-VN') ?? '—', icon: Droplets, color: 'green', note: 'Còn hạn sử dụng' },
    { label: 'Cơ sở kết nối', value: facilities.data?.length ?? '—', icon: Building2, color: 'blue', note: 'Trong mạng lưới' },
    { label: 'Sắp hết hạn trong 72 giờ', value: summary.data?.expiring_within_72h ?? '—', icon: Clock3, color: 'gold', note: 'Ưu tiên xuất trước' },
  ] as const

  return <>
    <div className="theme1-page-heading theme1-overview-heading">
      <div><span className="theme1-eyebrow"><Activity size={13} /> Trung tâm điều phối</span><h2>Tổng quan điều phối</h2><p>Theo dõi nhu cầu, nguồn máu và phản hồi SOS trên toàn mạng lưới.</p></div>
      <span className={`theme1-status-pill${connected ? '' : ' is-critical'}`}><i />{connected ? 'Đang đồng bộ' : health.isLoading ? 'Đang kết nối…' : 'Mất kết nối API'}</span>
    </div>

    <section className="theme1-kpis" aria-label="Chỉ số mạng lưới">
      {metricValues.map(({ label, value, icon: Icon, color, note }) => <article className={`theme1-kpi theme1-kpi-${color}`} key={label}>
        <span className="theme1-kpi-icon"><Icon size={21} /></span>
        <div><span className="theme1-kpi-label">{label}</span><strong>{value}</strong><small>{note}</small></div>
      </article>)}
    </section>

    <div className="theme1-dashboard-grid">
      <section className="theme1-panel theme1-preview-map">
        <div className="theme1-panel-title"><h3>Bản đồ nhu cầu máu</h3><Link to="/map">Mở bản đồ <ArrowRight size={14} /></Link></div>
        <Link className="theme1-map-preview" to="/map" aria-label="Mở bản đồ điều phối SOS">
          <img src="/map-original-crop.png" alt="Bản đồ điều phối và các cơ sở truyền máu tại Việt Nam" />
          <span className="theme1-map-live"><i /> {activeEvents.data?.length ?? 0} ca SOS đang mở</span>
        </Link>
        <div className="theme1-map-legend"><span><i className="legend-hospital" /> Cơ sở y tế</span><span><i className="legend-sos" /> Yêu cầu SOS</span><span><i className="legend-route" /> Tuyến điều phối</span></div>
      </section>

      <section className="theme1-panel theme1-sos-list">
        <div className="theme1-panel-title"><h3>Ca cần máu khẩn cấp</h3><Link to="/sos">Xem tất cả <ArrowRight size={14} /></Link></div>
        {activeEvents.isLoading ? <div className="theme1-empty" role="status">Đang tải tín hiệu SOS…</div> : activeEvents.data?.length ? <div className="theme1-event-list">
          {[...activeEvents.data].sort((a, b) => Date.parse(a.opened_at) - Date.parse(b.opened_at)).slice(0, 4).map(event => <Link to={`/sos?eventId=${encodeURIComponent(event.id)}`} className="theme1-event-row" key={event.id}>
            <span className="theme1-event-type">{eventBloodType(event)}</span>
            <span className="theme1-event-copy"><strong>{facilityName(event.facility_id)}</strong><small>{COMPONENT_SHORT[event.component_code ?? ''] ?? event.component_code ?? 'Chế phẩm máu'} · {event.accept_count}/{event.target_count} người đồng ý</small></span>
            <span className="theme1-event-time">{eventTime(event.opened_at)}</span>
          </Link>)}
        </div> : <div className="theme1-empty">Hiện chưa có ca SOS đang mở.<br /><Link to="/sos">Tạo tín hiệu SOS</Link></div>}
      </section>

      <section className="theme1-panel theme1-network">
        <div className="theme1-panel-title"><h3>Tình trạng mạng lưới</h3></div>
        <div className="theme1-network-summary"><span className={`theme1-network-ring${connected ? '' : ' is-offline'}`}><strong>{facilities.data?.length ?? '—'}</strong><small>cơ sở<br />trong mạng</small></span>
          <div className="theme1-network-legend"><span><i className="network-active" /> Hệ thống API<br /><strong>{connected ? 'Đang hoạt động' : 'Chưa kết nối'}</strong></span><span><i className="network-share" /> Cơ sở chia sẻ<br /><strong>{facilities.data?.filter(facility => facility.opt_in).length ?? '—'}</strong></span></div>
        </div>
        <h4 className="theme1-network-subhead">Nguồn máu theo chế phẩm</h4>
        {(summary.data?.by_component_status ?? []).filter(item => item.status === 'available').map(item => <div className="theme1-network-bar" key={item.component}>
          <div><span>{COMPONENT_SHORT[item.component] ?? item.component}</span><strong>{item.count.toLocaleString('vi-VN')}</strong></div><i><b style={{ width: `${Math.min(100, Math.max(6, item.count / Math.max(summary.data?.total_available ?? 1, 1) * 100))}%` }} /></i>
        </div>)}
      </section>
    </div>

    <section className="theme1-panel theme1-recent-activity">
      <div className="theme1-panel-title"><h3>Hoạt động gần đây</h3><Link to="/reports">Mở nhật ký <ArrowRight size={14} /></Link></div>
      {recentEvents.isLoading ? <div className="theme1-empty" role="status">Đang tải hoạt động…</div> : latestEvents.length ? <div className="table-wrap">
        <table><thead><tr><th>Thời gian</th><th>Hoạt động</th><th>Nội dung</th><th>Cơ sở</th><th>Trạng thái</th></tr></thead><tbody>
          {latestEvents.map(event => <tr key={event.id}><td>{new Date(event.opened_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</td><td><span className="theme1-activity-icon"><Droplets size={15} /></span> Tiếp nhận SOS</td><td>{eventBloodType(event)} · {COMPONENT_SHORT[event.component_code ?? ''] ?? event.component_code ?? 'Chế phẩm máu'} · cần {event.target_count} người hiến</td><td>{facilityName(event.facility_id)}</td><td><span className={`theme1-status-pill${event.status === 'open' ? ' is-critical' : ''}`}>{event.status === 'open' ? 'Đang mở' : event.status === 'fulfilled' ? 'Đã đủ người' : event.status === 'completed' ? 'Đã hoàn tất' : event.status === 'expired' ? 'Đã kết thúc' : event.status}</span></td></tr>)}
        </tbody></table>
      </div> : <div className="theme1-empty">Chưa có hoạt động SOS nào được ghi nhận.</div>}
    </section>
  </>
}
