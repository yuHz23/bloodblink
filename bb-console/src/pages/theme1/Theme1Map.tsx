import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ChevronDown, CircleAlert, Clock3, Droplets, MapPinned, Send, Siren } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type SosEvent } from '../../lib/api'
import { COMPONENT_SHORT } from '../../lib/constants'

const RING_LABELS = [
  { title: 'Vòng 1 · Khu vực gần', time: 'T+0', note: 'Người hiến cùng khu vực' },
  { title: 'Vòng 2 · Mở rộng', time: 'T+10', note: 'Mở rộng bán kính tìm kiếm' },
  { title: 'Vòng 3 · Toàn thành phố', time: 'T+25', note: 'Gửi thông báo trên toàn thành phố' },
  { title: 'Vòng 4 · Liên vùng', time: 'T+45', note: 'Kết nối các trung tâm lân cận' },
]

function displayBlood(event: SosEvent) { return event.abo ? `${event.abo}${event.rh ?? ''}` : 'Chưa rõ' }

export default function Theme1Map() {
  const client = useQueryClient()
  const [eventId, setEventId] = useState('')
  const facilities = useQuery({ queryKey: ['theme1-map-facilities'], queryFn: api.listFacilities, refetchInterval: 60_000 })
  const events = useQuery({ queryKey: ['theme1-map-open-sos'], queryFn: api.listOpenSosEvents, refetchInterval: 5_000, refetchIntervalInBackground: true })
  const allEvents = useQuery({ queryKey: ['theme1-map-recent-sos'], queryFn: api.listSosEvents, refetchInterval: 15_000, refetchIntervalInBackground: true })
  const activeEvents = useMemo(() => events.data ?? [], [events.data])
  const selected = activeEvents.find(event => event.id === eventId) ?? activeEvents[0]
  const facilityName = (id: string | null) => facilities.data?.find(item => item.id === id)?.name ?? 'Cơ sở chưa xác định'
  const escalate = useMutation({
    mutationFn: (id: string) => api.escalateSosEvent(id),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['theme1-map-open-sos'] }),
        client.invalidateQueries({ queryKey: ['theme1-map-recent-sos'] }),
        client.invalidateQueries({ queryKey: ['theme1-open-sos'] }),
      ])
    },
  })
  const nextRing = selected ? selected.ring + 1 : 0
  const latest = [...(allEvents.data ?? [])].sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at)).slice(0, 6)

  return <>
    <div className="theme1-page-heading"><div><span className="theme1-eyebrow"><MapPinned size={13} /> Điều phối trực quan</span><h2>Điều phối SOS</h2><p>Theo dõi các ca cần máu và tiến trình huy động người hiến theo vòng.</p></div><Link to="/matching" className="btn btn-secondary"><ArrowRight size={15} /> Điều phối nguồn máu</Link></div>

    {selected && <section className="theme1-case-strip">
      <div className="theme1-case-icon"><Siren size={22} /></div>
      <div className="theme1-case-cell"><small>CƠ SỞ YÊU CẦU</small><strong>{facilityName(selected.facility_id)}</strong></div>
      <div className="theme1-case-cell"><small>NHÓM MÁU</small><strong className="theme1-case-blood">{displayBlood(selected)}</strong></div>
      <div className="theme1-case-cell"><small>CHẾ PHẨM</small><strong>{COMPONENT_SHORT[selected.component_code ?? ''] ?? selected.component_code ?? 'Máu'}</strong></div>
      <div className="theme1-case-cell"><small>PHẢN HỒI</small><strong>{selected.accept_count}/{selected.target_count} người</strong></div>
      <span className="theme1-status-pill is-critical"><i /> {selected.urgency === 'emergency' ? 'CẤP CỨU' : 'ĐANG MỞ'}</span>
    </section>}

    <div className="theme1-map-layout">
      <section className="theme1-map-canvas" aria-label="Bản đồ điều phối Việt Nam">
        <img src="/map-original-crop.png" alt="Bản đồ các trung tâm truyền máu và cơ sở y tế tại Việt Nam" />
        <div className="theme1-map-caption"><span className="theme1-map-selector"><Droplets size={17} /> Hồng cầu lắng (RBC) <ChevronDown size={15} /></span><span className="theme1-map-scale">BẢN ĐỒ MINH HỌA · {activeEvents.length} CA SOS ĐANG MỞ</span></div>
      </section>

      <aside className="theme1-panel theme1-escalation" aria-label="Leo thang tìm người hiến">
        <div className="theme1-panel-title"><h3>Leo thang tìm người hiến</h3><span className="theme1-live-tag"><i /> TRỰC TIẾP</span></div>
        {events.isLoading ? <div className="theme1-empty" role="status">Đang tải ca SOS…</div> : activeEvents.length === 0 ? <div className="theme1-no-case"><CircleAlert size={23} /><strong>Chưa có ca SOS đang mở</strong><span>Các tín hiệu mới sẽ hiển thị tại đây.</span><Link className="btn btn-primary" to="/sos">Tạo ca SOS</Link></div> : <>
          {activeEvents.length > 1 && <label className="theme1-event-select-label" htmlFor="theme1-active-event">Ca SOS đang theo dõi</label>}
          {activeEvents.length > 1 && <select id="theme1-active-event" className="theme1-event-select" value={selected?.id ?? ''} onChange={event => setEventId(event.target.value)}>
            {activeEvents.map(event => <option value={event.id} key={event.id}>{facilityName(event.facility_id)} · {displayBlood(event)}</option>)}
          </select>}
          <div className="theme1-ring-progress"><strong>{selected?.accept_count ?? 0}</strong><span>/{selected?.target_count ?? 0} người hiến đồng ý</span><i><b style={{ width: `${selected?.target_count ? Math.min(100, selected.accept_count / selected.target_count * 100) : 0}%` }} /></i></div>
          <div className="theme1-ring-list">{RING_LABELS.map((ring, index) => <div className={`theme1-ring-step${selected?.ring === index ? ' is-current' : selected && selected.ring > index ? ' is-done' : ''}`} key={ring.time}>
            <span className="theme1-ring-number">{index + 1}</span><div><strong>{ring.title}</strong><small>{ring.note}</small></div><span className="theme1-ring-time">{ring.time}</span>
          </div>)}</div>
          <button className="btn btn-primary theme1-escalate-button" disabled={!selected || selected.ring >= 3 || escalate.isPending} onClick={() => selected && escalate.mutate(selected.id)}>
            <Send size={15} /> {escalate.isPending ? 'Đang gửi thông báo…' : selected?.ring === 3 ? 'Đã đến vòng cuối' : `Gửi vòng ${nextRing + 1} tiếp theo`}
          </button>
          {escalate.error && <p className="theme1-inline-error" role="alert">{escalate.error.message}</p>}
          {escalate.isSuccess && <p className="theme1-inline-success" role="status">Đã chuyển ca SOS sang vòng tiếp theo.</p>}
        </>}
        <Link className="theme1-escalation-link" to={selected ? `/sos?eventId=${encodeURIComponent(selected.id)}` : '/sos'}>Mở bảng điều khiển SOS <ArrowRight size={14} /></Link>
      </aside>
    </div>

    <section className="theme1-panel theme1-timeline-panel">
      <div className="theme1-panel-title"><h3><Clock3 size={17} /> Dòng thời gian SOS</h3><Link to="/sos">Xem toàn bộ <ArrowRight size={14} /></Link></div>
      {allEvents.isLoading ? <div className="theme1-empty" role="status">Đang tải nhật ký SOS…</div> : latest.length ? <div className="theme1-sos-timeline">{latest.map((event, index) => <article className="theme1-timeline-event" key={event.id}>
        <span className={`theme1-timeline-dot${event.status === 'open' ? ' is-open' : ''}`} />
        <div><time>{new Date(event.opened_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</time><strong>{index === 0 && event.status === 'open' ? 'Đang huy động người hiến' : event.status === 'completed' ? 'Xác nhận hoàn tất' : event.status === 'fulfilled' ? 'Đã đủ người đồng ý' : event.status === 'expired' ? 'Ca SOS đã kết thúc' : 'Tạo yêu cầu SOS'}</strong><small>{facilityName(event.facility_id)} · {displayBlood(event)} · vòng {event.ring + 1}</small></div>
      </article>)}</div> : <div className="theme1-empty">Chưa có sự kiện SOS nào.</div>}
    </section>
  </>
}
