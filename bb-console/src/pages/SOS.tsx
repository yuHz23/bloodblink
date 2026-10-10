import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Siren, Clock, Users, ArrowUpRight, CheckCircle2, Phone, ShieldAlert } from 'lucide-react'
import { api, type SosNotification, type SosResponder, type SosReward } from '../lib/api'
import { useAuth } from '../lib/auth'
import { URGENCY_LABELS, COMPONENT_LABELS } from '../lib/constants'

/**
 * SOS — Huy động người hiến theo 4 vòng.
 *
 * P1: trang này trước đây là bản dựng tĩnh, không gọi API nào. Nay nó thực sự
 * mở lời kêu gọi trên bb-core và theo dõi số người đã nhận lời.
 *
 * Ring 0 (T+0): cùng nhóm máu, ~1 km
 * Ring 1 (T+10): nhóm tương hợp, ~3 km
 * Ring 2 (T+25): mở rộng, ~5 km
 * Ring 3 (T+45): toàn thành phố
 */
const RINGS = [
  { ring: 0, label: 'Vòng 0 — Cùng nhóm máu', radius: '~1 km', time: 'T+0 phút', color: '#3b82f6' },
  { ring: 1, label: 'Vòng 1 — Tương hợp', radius: '~3 km', time: 'T+10 phút', color: '#f59e0b' },
  { ring: 2, label: 'Vòng 2 — Mở rộng', radius: '~5 km', time: 'T+25 phút', color: '#ef4444' },
  { ring: 3, label: 'Vòng 3 — Toàn viện', radius: 'Toàn TP.HCM', time: 'T+45 phút', color: '#7c3aed' },
]
const SOS_TRACKING_STORAGE_KEY = 'bb_sos_tracking'

export default function SOS() {
  const { session } = useAuth()
  const queryClient = useQueryClient()

  const [abo, setAbo] = useState('O')
  const [rh, setRh] = useState('+')
  const [component, setComponent] = useState('WB')
  const [urgency, setUrgency] = useState('emergency')
  const [qty, setQty] = useState(2)
  const [ring, setRing] = useState(0)
  const [eventId, setEventId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('eventId'))
  const [trackingDismissed, setTrackingDismissed] = useState(() => {
    try { return window.localStorage.getItem(SOS_TRACKING_STORAGE_KEY) === 'disabled' } catch { return false }
  })
  const [lastMessage, setLastMessage] = useState<string | null>(null)

  const stopTracking = () => {
    setEventId(null)
    setRing(0)
    setTrackingDismissed(true)
    try { window.localStorage.setItem(SOS_TRACKING_STORAGE_KEY, 'disabled') } catch { /* Keep the choice for this page. */ }
  }
  const followEvent = (id: string, eventRing: number) => {
    setTrackingDismissed(false)
    setEventId(id)
    setRing(eventRing)
    try { window.localStorage.removeItem(SOS_TRACKING_STORAGE_KEY) } catch { /* Keep the choice for this page. */ }
  }

  const { data: facilities } = useQuery({
    queryKey: ['facilities'],
    queryFn: () => api.listFacilities(),
  })

  const facility = facilities?.find(f => f.id === session?.facilityId) ?? facilities?.[0]

  // Trạng thái lời kêu gọi đang mở — hỏi lại mỗi 5 giây, KỂ CẢ khi cửa sổ bị che.
  //
  // React Query mặc định dừng `refetchInterval` lúc `document.hidden`. Với một
  // bảng điều phối cấp cứu thì đó đúng là lúc không được dừng: người trực gọi
  // điện, mở bệnh án, alt-tab sang cửa sổ khác — quay lại thấy vòng và số người
  // đã gọi đứng nguyên từ lúc rời đi, trong khi màn hình vẫn ghi "tự cập nhật
  // mỗi 5 giây". Ba truy vấn của trang này chỉ chạy khi có sự kiện đang mở nên
  // không phải là nền tải suốt ngày.
  const { data: event } = useQuery({
    queryKey: ['sos-event', eventId],
    queryFn: () => api.getSosEvent(eventId!),
    enabled: !!eventId,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const open = useMutation({
    mutationFn: () => api.createSosEvent({
      facility_id: facility?.id,
      component_code: component,
      abo, rh, urgency, qty,
      ring: 0,
      h3_cell: facility?.h3_cell ?? undefined,
    }),
    onSuccess: (ev) => {
      setEventId(ev.id)
      setTrackingDismissed(false)
      try { window.localStorage.removeItem(SOS_TRACKING_STORAGE_KEY) } catch { /* Keep tracking this new SOS on this page. */ }
      setLastMessage(ev.message)
      setRing(ev.ring)
    },
  })

  // Leo thang trên CHÍNH sự kiện đó. Bản trước tạo một sự kiện MỚI cho mỗi vòng,
  // nên lịch sử "ai đã được gọi" vỡ thành bốn mảnh và người ở vòng 0 bị gọi lại.
  const escalate = useMutation({
    mutationFn: () => api.escalateSosEvent(eventId!),
    onSuccess: (ev) => {
      setLastMessage(ev.message)
      setRing(ev.ring)
    },
  })

  const { data: notifications } = useQuery({
    queryKey: ['sos-notifications', eventId],
    queryFn: () => api.listSosNotifications(eventId!),
    enabled: !!eventId,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const { data: responders } = useQuery({
    queryKey: ['sos-responders', eventId],
    queryFn: () => api.listSosResponders(eventId!),
    enabled: !!eventId,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const { data: rewards } = useQuery({
    queryKey: ['sos-rewards', eventId],
    queryFn: () => api.listSosRewards(eventId!),
    enabled: !!eventId,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })
  const rewardByDonor = new Map<string, SosReward>(
    (rewards ?? []).map((reward: SosReward): [string, SosReward] => [reward.donor_id, reward]),
  )
  const pendingDonationCount = (responders ?? []).filter(responder => {
    const status = rewardByDonor.get(responder.donor_id)?.status
    return !['compensation_proposed', 'mock_ready', 'not_completed'].includes(status ?? '')
  }).length
  const canComplete = event !== undefined
    && ['fulfilled', 'expired'].includes(event.status)
    && responders !== undefined
    && rewards !== undefined
    && pendingDonationCount === 0

  const refreshRewardData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['sos-rewards', eventId] }),
      queryClient.invalidateQueries({ queryKey: ['sos-responders', eventId] }),
      queryClient.invalidateQueries({ queryKey: ['sos-event-history'] }),
    ])
  }
  const confirmDonation = useMutation({
    mutationFn: (args: { donorId: string; donated: boolean }) =>
      api.confirmSosDonation(eventId!, args.donorId, args.donated),
    onSuccess: refreshRewardData,
  })
  const chooseBackup = useMutation({
    mutationFn: (args: { donorId: string; choice: 'continue' | 'decline' }) =>
      api.chooseSosBackup(eventId!, args.donorId, args.choice),
    onSuccess: refreshRewardData,
  })

  const complete = useMutation({
    mutationFn: () => api.completeSosEvent(eventId!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sos-event', eventId] }),
        queryClient.invalidateQueries({ queryKey: ['sos-event-history'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-responders', eventId] }),
        queryClient.invalidateQueries({ queryKey: ['sos-rewards', eventId] }),
      ])
    },
  })

  // Recent event history includes fulfilled SOS events so accepted donors stay
  // visible to admins long enough to verify the actual donation.
  const { data: sosEvents } = useQuery({
    queryKey: ['sos-event-history'],
    queryFn: api.listSosEvents,
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
  })

  useEffect(() => {
    if (eventId || trackingDismissed || !sosEvents?.length) return
    const latestTrackable = sosEvents.find(ev => ['open', 'fulfilled', 'expired'].includes(ev.status))
    if (!latestTrackable) return
    setEventId(latestTrackable.id)
    setRing(latestTrackable.ring)
  }, [eventId, sosEvents, trackingDismissed])

  useEffect(() => {
    const url = new URL(window.location.href)
    if (eventId) url.searchParams.set('eventId', eventId)
    else url.searchParams.delete('eventId')
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
  }, [eventId])

  const activeRing = event?.ring ?? (eventId ? ring : null)

  // Số người ĐÃ GỌI phải đọc từ dữ liệu đang hỏi lại 5 giây/lần, không giữ trong
  // state cục bộ: state chỉ được ghi trong `onSuccess` của hai nút mở/leo thang,
  // nên khi bộ lập lịch tự nâng vòng ở T+10/25/45 thì ô "Vòng hiện tại" nhảy lên
  // còn ô này đứng nguyên ở số của vòng đầu — và mâu thuẫn ngay với dòng
  // "Đã gọi N người hiến" ở bảng bên dưới.
  const notified = notifications?.length ?? event?.donors_notified ?? null

  return (
    <>
      <h2>SOS — Huy động người hiến máu</h2>
      <p className="subtitle">Leo thang 4 vòng · Ô lưới H3 ~1 km có TTL · Không lưu tọa độ thô</p>

      {/* Mở lời kêu gọi */}
      <div className="card">
        <h3 style={{ marginBottom: 14 }}>Mở lời kêu gọi</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Nhóm máu cần</label>
            <select value={abo} onChange={e => setAbo(e.target.value)}>
              {['O', 'A', 'B', 'AB'].map(g => <option key={g} value={g}>Nhóm {g}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>RhD</label>
            <select value={rh} onChange={e => setRh(e.target.value)}>
              <option value="+">RhD⁺</option>
              <option value="-">RhD⁻</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Chế phẩm</label>
            <select value={component} onChange={e => setComponent(e.target.value)}>
              {Object.entries(COMPONENT_LABELS).map(([code, label]) =>
                <option key={code} value={code}>{label}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Mức khẩn</label>
            <select value={urgency} onChange={e => setUrgency(e.target.value)}>
              {Object.entries(URGENCY_LABELS).map(([code, u]) =>
                <option key={code} value={code}>{u.label} — {u.desc}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Số người cần</label>
            <input type="number" min={1} max={20} value={qty}
                   onChange={e => setQty(Number(e.target.value) || 1)} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 16 }}>
          <button className="btn btn-danger" disabled={!facility || open.isPending}
                  onClick={() => open.mutate()}>
            <Siren size={15} /> {open.isPending ? 'Đang mở…' : 'Mở SOS từ vòng 0'}
          </button>
          {facility && (
            <span style={{ fontSize: 12, color: 'var(--bb-gray-500)' }}>
              Phát từ {facility.name} · ô lưới{' '}
              <code style={{ fontFamily: 'var(--font-mono)' }}>{facility.h3_cell}</code>
            </span>
          )}
        </div>

        {open.error && (
          <div style={{ background: '#fee2e2', color: '#b91c1c', borderRadius: 8,
                        padding: '10px 12px', fontSize: 13, marginTop: 12 }}>
            {open.error instanceof Error ? open.error.message : 'Không mở được lời kêu gọi'}
          </div>
        )}
      </div>

      {/* Recent SOS calls remain available after fulfillment for donation verification. */}
      {sosEvents && sosEvents.length > 0 && (
        <div className="card">
          <h3 style={{ marginBottom: 4 }}>SOS gần đây trong cụm ({sosEvents.length})</h3>
          <p style={{ fontSize: 12.5, color: 'var(--bb-gray-500)', marginTop: 0, marginBottom: 12 }}>
            Bao gồm ca đang phát và ca đã đủ người nhận lời để cơ sở xác nhận kết quả hiến.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Cần</th>
                  <th>Mức khẩn</th>
                  <th>Vòng</th>
                  <th>Đã nhận lời</th>
                  <th>Trạng thái</th>
                  <th>Mã sự kiện</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sosEvents.map(ev => (
                  <tr key={ev.id} style={ev.id === eventId ? { background: 'var(--bb-red-soft, #fef2f2)' } : undefined}>
                    <td style={{ fontWeight: 600 }}>
                      {ev.abo ?? '?'}{ev.rh ?? ''} ·{' '}
                      {(ev.component_code && COMPONENT_LABELS[ev.component_code]) || ev.component_code || '—'}
                    </td>
                    <td>
                      <span className={`badge badge-${ev.urgency === 'emergency' ? 'urgent' : 'routine'}`}>
                        {(ev.urgency && URGENCY_LABELS[ev.urgency]?.label) || ev.urgency || '—'}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{ev.ring}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {ev.accept_count}/{ev.target_count}
                    </td>
                    <td>{ev.status === 'open' ? 'Đang phát' : ev.status === 'fulfilled' ? 'Đã đủ người' : ev.status === 'expired' ? 'Hết hạn' : ev.status}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {ev.id.slice(0, 8)}…
                    </td>
                    <td>
                      <button className="btn" style={{ fontSize: 12, padding: '4px 12px' }}
                              onClick={() => followEvent(ev.id, ev.ring)}>
                        {ev.id === eventId ? 'Đang xem' : 'Theo dõi'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {trackingDismissed && !eventId && (
        <div className="card" role="status">
          Đã dừng theo dõi chi tiết. Các ca SOS vẫn tiếp tục hoạt động; chọn “Theo dõi” trong danh sách khi cần mở lại.
        </div>
      )}

      {/* SOS details and verified donor outcomes */}
      {eventId && (
        <div className="card" style={{ borderLeft: '3px solid var(--bb-red)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h3>{event?.status === 'completed' ? 'Ca SOS đã hoàn tất' : event?.status === 'fulfilled' ? 'SOS đã đủ người nhận lời' : 'Chi tiết SOS'}</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className={`badge ${['fulfilled', 'completed'].includes(event?.status ?? '') ? 'badge-normal' : 'badge-urgent'}`}>
                {event?.status === 'fulfilled' ? 'Đã đủ người' : event?.status === 'completed' ? 'Đã hoàn tất' : event?.status === 'expired' ? 'Đã hết hạn' : event?.status === 'cancelled' ? 'Đã hủy' : event?.status === 'open' ? 'Đang chờ' : event?.status ?? 'Đang tải'}
              </span>
              {event && !['completed', 'cancelled'].includes(event.status) &&
                (session?.role === 'admin' || (!!event.facility_id && session?.facilityId === event.facility_id)) && (
                  <button
                    className="btn btn-danger"
                    type="button"
                    disabled={complete.isPending || !canComplete}
                    onClick={() => complete.mutate()}
                  >
                    {complete.isPending ? 'Đang hoàn tất…' : 'Hoàn tất ca'}
                  </button>
                )}
              <button className="btn btn-secondary" type="button" onClick={stopTracking}>Tắt theo dõi</button>
            </div>
          </div>

          {complete.error && <p role="alert" style={{ color: 'var(--bb-red)' }}>{complete.error.message}</p>}
          {event && !['completed', 'cancelled'].includes(event.status) && !canComplete && (
            <p role="status" style={{ color: 'var(--text-muted)', fontSize: 12.5 }}>
              {!['fulfilled', 'expired'].includes(event.status)
                ? 'Ca cần dừng tuyển người hiến trước khi hoàn tất.'
                : responders === undefined || rewards === undefined
                  ? 'Đang tải xác nhận hiến và phương án hỗ trợ.'
                  : `Còn ${pendingDonationCount} người nhận lời cần xử lý trước khi hoàn tất ca.`}
            </p>
          )}

          <div className="stat-grid" style={{ marginTop: 14 }}>
            <div className="stat-card">
              <div className="stat-label">Vòng hiện tại</div>
              <div className="stat-number">{event?.ring ?? ring}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Đã gọi</div>
              <div className="stat-number">{notified ?? '—'}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Đã nhận lời</div>
              <div className="stat-number">
                {event ? `${event.accept_count}/${event.target_count}` : '—'}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Nhóm máu</div>
              <div className="stat-number" style={{ fontSize: 26 }}>{abo}{rh}</div>
            </div>
          </div>

          {/* Câu mô tả này do lần mở/leo thang GẦN NHẤT sinh ra, nên chỉ còn đúng
              khi sự kiện vẫn ở đúng vòng đó. Máy chủ tự nâng vòng ở T+10/25/45 mà
              vẫn hiện câu cũ thì nó nói "vòng 0, tìm được 8 người" ngay bên dưới
              ô "Vòng hiện tại: 1" — cùng kiểu lệch với ô "Đã gọi" trước đây. */}
          {lastMessage && (event?.ring ?? ring) === ring && (
            <p style={{ fontSize: 13, color: 'var(--bb-gray-600)', marginTop: 12 }}>{lastMessage}</p>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 14, alignItems: 'center' }}>
            {(event?.ring ?? ring) < 3 && event?.status === 'open' && (
              <button className="btn btn-primary" disabled={escalate.isPending}
                      onClick={() => escalate.mutate()}>
                <ArrowUpRight size={15} />
                {escalate.isPending ? 'Đang nâng vòng…' : `Leo thang lên vòng ${(event?.ring ?? ring) + 1}`}
              </button>
            )}
            {event?.status === 'fulfilled' && (
              <span style={{ display: 'flex', gap: 6, alignItems: 'center',
                             color: 'var(--bb-green, #059669)', fontSize: 13, fontWeight: 600 }}>
                <CheckCircle2 size={16} /> Đã đủ số người hiến nhận lời
              </span>
            )}
            <span style={{ fontSize: 12, color: 'var(--bb-gray-400)' }}>
              Mã sự kiện <code style={{ fontFamily: 'var(--font-mono)' }}>{eventId.slice(0, 8)}</code> ·
              tự cập nhật mỗi 5 giây
            </span>
          </div>

          <p style={{ fontSize: 12, color: 'var(--bb-gray-400)', marginTop: 12 }}>
            Máy chủ <strong>tự nâng vòng</strong> theo mốc T+10/25/45 phút; nút trên chỉ để nâng
            sớm. Mỗi người hiến chỉ được gọi một lần cho cả lời kêu gọi, dù nó đi qua nhiều vòng.
          </p>

          {/* Người đã nhận lời — nơi duy nhất lộ ra cách liên hệ */}
          {responders && responders.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
                <CheckCircle2 size={15} color="var(--bb-green)" />
                {responders.length} người đã nhận lời
              </h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Mã người hiến</th><th>Nhóm máu</th><th>Liên hệ</th><th>Ghi chú</th><th>Nhận lời</th><th>Xác nhận hiến & quà demo</th></tr>
                  </thead>
                  <tbody>
                    {responders.map((r: SosResponder) => {
                      const reward = rewardByDonor.get(r.donor_id)
                      return <tr key={r.donor_id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.donor_id}</td>
                        <td style={{ fontWeight: 700 }}>{r.blood_type ?? '—'}</td>
                        <td>
                          {r.contact_phone
                            ? <a href={`tel:${r.contact_phone}`}
                                 style={{ display: 'inline-flex', alignItems: 'center', gap: 5,
                                          color: 'var(--bb-blue)', fontWeight: 600 }}>
                                <Phone size={13} /> {r.contact_phone}
                              </a>
                            : <span style={{ color: 'var(--bb-gray-400)', fontSize: 12 }}>
                                Không chia sẻ số
                              </span>}
                        </td>
                        <td style={{ fontSize: 12, color: 'var(--bb-gray-600)' }}>{r.contact_note ?? '—'}</td>
                        <td style={{ fontSize: 12, color: 'var(--bb-gray-500)' }}>
                          Đã đồng ý · {new Date(r.responded_at).toLocaleTimeString('vi-VN')}
                        </td>
                        <td style={{ minWidth: 230 }}>
                          {!rewards ? <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Đang tải trạng thái…</span>
                            : !reward || reward.status === 'awaiting_donation' ? (
                              <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                                <button className="btn btn-primary" disabled={confirmDonation.isPending || event?.status === 'cancelled'}
                                  onClick={() => confirmDonation.mutate({ donorId: r.donor_id, donated: true })}>
                                  Xác nhận đã hiến
                                </button>
                                <button className="btn btn-secondary" disabled={confirmDonation.isPending || event?.status === 'cancelled'}
                                  onClick={() => confirmDonation.mutate({ donorId: r.donor_id, donated: false })}>
                                  Chưa hoàn tất
                                </button>
                              </span>
                            ) : reward.status === 'awaiting_choice' ? (
                              <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                                <button className="btn btn-secondary" disabled={chooseBackup.isPending || event?.status === 'cancelled'}
                                  onClick={() => chooseBackup.mutate({ donorId: r.donor_id, choice: 'continue' })}>
                                  Tiếp tục
                                </button>
                                <button className="btn btn-secondary" disabled={chooseBackup.isPending || event?.status === 'cancelled'}
                                  onClick={() => chooseBackup.mutate({ donorId: r.donor_id, choice: 'decline' })}>
                                  Dừng
                                </button>
                              </span>
                            ) : reward.status === 'mock_ready' ? (
                              <span style={{ color: 'var(--bb-green)', fontSize: 12 }}>
                                Đã xác nhận · quà demo {reward.proposed_amount_vnd?.toLocaleString('vi-VN')}đ
                              </span>
                            ) : reward.status === 'compensation_proposed' ? (
                              <span style={{ fontSize: 12 }}>Đã dừng · quà bù demo</span>
                            ) : <span style={{ fontSize: 12 }}>Chưa hoàn tất hiến</span>}
                        </td>
                      </tr>
                    })}
                  </tbody>
                </table>
              </div>
              {(chooseBackup.isError || confirmDonation.isError) && (
                <p role="alert" style={{ color: 'var(--bb-red)', fontSize: 12 }}>
                  {(chooseBackup.error ?? confirmDonation.error)?.message}
                </p>
              )}
              {/* Câu chú thích phải nằm trong MỘT <span>.
                  Thẻ bọc là flex container, nên nếu để text trần cạnh <strong> thì mỗi
                  mảnh trở thành một flex item riêng: câu bị xé thành ba cột và dấu chấm
                  cuối câu văng hẳn ra lề phải. */}
              <p style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 8,
                          display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                <ShieldAlert size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>
                  Số điện thoại do chính người hiến nhập lúc nhận lời — máy chủ không có sẵn số
                  của ai để mà lộ. Chỉ cơ sở phát lời kêu gọi đọc được, và <strong>mỗi lần mở
                  bảng này đều được ghi vào nhật ký ghi vết</strong>.
                </span>
              </p>
            </div>
          )}

          {notifications && notifications.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ marginBottom: 8 }}>
                Đã gọi {notifications.length} người hiến
              </h4>
              <div className="table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}>
                <table>
                  <thead>
                    <tr><th>Mã người hiến</th><th>Vòng</th><th>Kênh</th><th>Trạng thái</th><th>Lúc</th></tr>
                  </thead>
                  <tbody>
                    {notifications.map((n: SosNotification) => (
                      <tr key={n.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{n.donor_id}</td>
                        <td style={{ textAlign: 'center' }}>{n.ring}</td>
                        <td style={{ fontSize: 12 }}>
                          {n.channel === 'store' ? 'Hộp thư trong app' : n.channel.toUpperCase()}
                        </td>
                        <td>
                          <span className={`badge ${
                            n.status === 'read' ? 'badge-normal'
                            : n.status === 'failed' ? 'badge-critical' : 'badge-routine'}`}>
                            {n.status === 'read' ? 'Đã trả lời'
                             : n.status === 'sent' ? 'Đã gửi'
                             : n.status === 'failed' ? 'Lỗi gửi' : 'Chờ'}
                          </span>
                        </td>
                        <td style={{ fontSize: 12, color: 'var(--bb-gray-500)' }}>
                          {new Date(n.created_at).toLocaleTimeString('vi-VN')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 12, color: 'var(--bb-gray-400)', marginTop: 8 }}>
                Kênh "Hộp thư trong app": dự án chưa có Firebase, nên lời kêu gọi nằm chờ trong
                hộp thư và app BB-SOS hỏi mỗi 45 giây rồi tự dựng thông báo trên máy.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Các vòng huy động */}
      <div className="card">
        <h3 style={{ marginBottom: 16 }}>Các vòng huy động</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {RINGS.map(r => (
            <div key={r.ring} style={{
              background: activeRing !== null && r.ring <= activeRing ? `${r.color}15` : 'var(--bb-gray-50)',
              border: `2px solid ${activeRing !== null && r.ring <= activeRing ? r.color : 'var(--bb-gray-200)'}`,
              borderRadius: 10, padding: '14px 12px', textAlign: 'center', transition: 'all 0.15s',
            }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: r.color }}>{r.ring}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: r.color, marginTop: 4 }}>{r.time}</div>
              <div style={{ fontSize: 12, color: 'var(--bb-gray-600)', marginTop: 6 }}>{r.label}</div>
              <div style={{ fontSize: 11, color: 'var(--bb-gray-400)', marginTop: 2 }}>{r.radius}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Ràng buộc quyền riêng tư */}
      <div className="card" style={{ borderLeft: '3px solid var(--bb-blue)' }}>
        <h4 style={{ marginBottom: 8 }}>Ràng buộc quyền riêng tư</h4>
        <div style={{ fontSize: 13, color: 'var(--bb-gray-600)', lineHeight: 1.7 }}>
          <p>• <strong>Ô lưới H3 (độ phân giải ~1,2 km)</strong> thay vì tọa độ thô — vị trí người hiến chỉ được lưu dưới dạng ô lưới có thời hạn sống (TTL 4 giờ), không phải tọa độ GPS.</p>
          <p>• <strong>Máy chủ phán quyết khoảng cách hiến</strong> — app BB-SOS chỉ hiển thị; bb-core mới là nơi loại người chưa đủ 12 tuần (máu toàn phần) hoặc 2 tuần (tiểu cầu) theo Điều 6 TT 26/2013/TT-BYT.</p>
          <p>• <strong>Không lưu bệnh án</strong> — chỉ có chỉ mục và mã yêu cầu. Danh sách trả về cho cơ sở y tế không có họ tên hay số điện thoại.</p>
          <p style={{ marginTop: 8, color: 'var(--bb-red)', fontWeight: 600 }}>
            O⁻ chỉ chiếm ~0,1% dân số Việt Nam — hệ thống phạt nặng việc dùng O⁻ cho người không thuộc nhóm này.
          </p>
        </div>
      </div>

      {/* Khoảng cách hiến */}
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Khoảng cách hiến máu (Điều 6 TT 26/2013/TT-BYT)</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Loại hiến</th><th>Khoảng cách tối thiểu</th><th>Nơi kiểm tra</th></tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ fontWeight: 600 }}>Máu toàn phần / Khối hồng cầu</td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>12 tuần</td>
                <td><span className="badge badge-normal">bb-core</span></td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>Tiểu cầu / Huyết tương</td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>2 tuần</td>
                <td><span className="badge badge-normal">bb-core</span></td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>Bạch cầu hạt trung tính</td>
                <td style={{ fontFamily: 'var(--font-mono)' }}>≤3 lần / 7 ngày</td>
                <td><span className="badge badge-warning">Biên an toàn 7 ngày</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 8 }}>
          Ngưỡng áp theo <strong>chế phẩm đang cần</strong>, không phải một mốc 12 tuần duy nhất —
          nếu không sẽ chặn oan người hiến tiểu cầu (chỉ cần cách 2 tuần).
        </p>
      </div>

      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--bb-gray-400)', marginTop: 4 }}>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}><Clock size={13} /> Mốc leo thang T+0/10/25/45</span>
        <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}><Users size={13} /> Xem lớp người hiến trên Bản đồ</span>
      </div>
    </>
  )
}
