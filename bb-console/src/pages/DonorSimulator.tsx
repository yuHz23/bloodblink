import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CircleHelp, Gift, Heart, HeartHandshake, MapPin, Radio, X } from 'lucide-react'
import { api, type SosEvent, type SosNotification, type SosResponder, type SosReward } from '../lib/api'
import './Simulation.css'

type Outcome = 'accepted' | 'declined'
type Invitation = {
  event: SosEvent
  notification: SosNotification
  priorOutcome?: Outcome
  reward?: SosReward
  locationSharingConsented?: boolean | null
}
type SavedResponse = { outcome: Outcome; locationSharingConsented?: boolean | null }

function invitationKey(eventId: string, donorId: string) {
  return `${eventId}:${donorId}`
}

export default function DonorSimulator() {
  const client = useQueryClient()
  const [localResponses, setLocalResponses] = useState<Record<string, SavedResponse>>(() => {
    try { return JSON.parse(localStorage.getItem('bb_citizen_sim_responses') ?? '{}') }
    catch { return {} }
  })
  const [locationError, setLocationError] = useState<string | null>(null)
  const [vouchers, setVouchers] = useState<Record<string, 'gotit' | 'urbox'>>({})
  const dialogRef = useRef<HTMLElement | null>(null)

  const events = useQuery({ queryKey: ['sim-open-sos'], queryFn: api.listSosEvents, refetchInterval: 4000 })
  const activeEvents = useMemo(
    () => [...(events.data ?? [])]
      .filter(event => event.status === 'open' || event.status === 'fulfilled')
      .sort((a, b) => {
        const aFinalRound = a.status === 'open' && a.ring >= 3 ? 1 : 0
        const bFinalRound = b.status === 'open' && b.ring >= 3 ? 1 : 0
        return bFinalRound - aFinalRound || Date.parse(b.opened_at) - Date.parse(a.opened_at)
      })
      .slice(0, 1),
    [events.data],
  )
  const notificationQueries = useQueries({
    queries: activeEvents.map(event => ({
      queryKey: ['sim-donor-invitations', event.id],
      queryFn: () => api.listSosNotifications(event.id),
      refetchInterval: 3000,
    })),
  })
  const responderQueries = useQueries({
    queries: activeEvents.map(event => ({
      queryKey: ['sim-donor-responses', event.id],
      queryFn: () => api.listSosResponders(event.id),
      refetchInterval: 3000,
    })),
  })
  const rewardQueries = useQueries({
    queries: activeEvents.map(event => ({
      queryKey: ['sim-donor-rewards', event.id],
      queryFn: () => api.listSosRewards(event.id),
      refetchInterval: 3000,
    })),
  })

  const invitations = useMemo(() => {
    const items = new Map<string, Invitation>()
    activeEvents.forEach((event, index) => {
      const responders = new Map(
        (responderQueries[index]?.data ?? []).map((responder: SosResponder) => [responder.donor_id, responder]),
      )
      for (const notification of notificationQueries[index]?.data ?? []) {
        if (notification.status === 'failed') continue
        const key = invitationKey(event.id, notification.donor_id)
        const response = responders.get(notification.donor_id)
        if (event.status !== 'open' && response?.outcome !== 'accepted') continue
        // In this simulator, a resident is surfaced only when the campaign
        // reaches its fourth and final round. Keep earlier accepted responses
        // visible so a hospital can still confirm the donation and reward it.
        if (notification.ring !== 3 && response?.outcome !== 'accepted') continue
        const saved = localResponses[key]
        const outcome = saved?.outcome ?? response?.outcome
        const priorOutcome = outcome === 'accepted' || outcome === 'declined' ? outcome : undefined
        const locationSharingConsented = saved?.locationSharingConsented ?? response?.location_sharing_consented ?? null
        const reward = (rewardQueries[index]?.data ?? []).find((item: SosReward) => item.donor_id === notification.donor_id)
        items.set(key, { event, notification, priorOutcome, reward, locationSharingConsented })
      }
    })
    return [...items.entries()].map(([key, invitation]) => ({ key, ...invitation }))
  }, [activeEvents, notificationQueries, responderQueries, rewardQueries, localResponses])

  useEffect(() => {
    try { localStorage.setItem('bb_citizen_sim_responses', JSON.stringify(localResponses)) } catch { /* optional demo state */ }
  }, [localResponses])

  const respond = useMutation({
    mutationFn: ({ invitation, outcome, shareLocation, latitude, longitude }: {
      invitation: Invitation
      outcome: Outcome
      shareLocation?: boolean
      latitude?: number
      longitude?: number
    }) => api.respondToSosEvent(invitation.event.id, {
      donor_id: invitation.notification.donor_id,
      outcome,
      ...(shareLocation !== undefined ? { share_location: shareLocation } : {}),
      ...(latitude !== undefined ? { latitude } : {}),
      ...(longitude !== undefined ? { longitude } : {}),
    }),
    onSuccess: async (result, variables) => {
      const key = invitationKey(variables.invitation.event.id, variables.invitation.notification.donor_id)
      setLocalResponses(previous => ({
        ...previous,
        [key]: { outcome: variables.outcome, locationSharingConsented: result.location_sharing_consented },
      }))
      const eventId = variables.invitation.event.id
      await Promise.all([
        client.invalidateQueries({ queryKey: ['sim-open-sos'] }),
        client.invalidateQueries({ queryKey: ['sim-donor-invitations', eventId] }),
        client.invalidateQueries({ queryKey: ['sim-donor-responses', eventId] }),
        client.invalidateQueries({ queryKey: ['sim-donor-rewards', eventId] }),
        client.invalidateQueries({ queryKey: ['open-sos'] }),
      ])
    },
  })

  const shareCurrentLocation = (invitation: Invitation) => {
    if (!navigator.geolocation) {
      setLocationError('Trình duyệt không hỗ trợ chia sẻ vị trí.')
      return
    }
    setLocationError(null)
    navigator.geolocation.getCurrentPosition(
      position => respond.mutate({
        invitation,
        outcome: 'accepted',
        shareLocation: true,
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      }),
      error => setLocationError(error.code === error.PERMISSION_DENIED
        ? 'Bạn chưa cho phép trình duyệt truy cập vị trí. Lời nhận hiến vẫn được giữ.'
        : 'Không lấy được vị trí hiện tại. Lời nhận hiến vẫn được giữ.'),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
    )
  }

  const acceptedNeedingFollowup = invitations.find(item =>
    item.priorOutcome === 'accepted'
      && (!item.reward
        || item.reward.status === 'awaiting_choice'
        || item.reward.status === 'awaiting_donation'
        || (item.reward.status === 'mock_ready' && !vouchers[item.key])),
  )
  const currentInvitation = acceptedNeedingFollowup
    ?? invitations.find(item => item.event.status === 'open'
      && item.notification.ring === 3
      && !item.priorOutcome
      && item.notification.status !== 'read')
    ?? invitations.find(item => item.notification.ring === 3)
    ?? invitations.find(item => item.priorOutcome === 'accepted')
  const currentOutcome = currentInvitation?.priorOutcome
  const currentReward = currentInvitation?.reward
  const notificationAlreadyRead = currentInvitation?.notification.status === 'read'
  const showSosPopup = !!currentInvitation && !currentOutcome && !notificationAlreadyRead
  const showLocationPopup = currentOutcome === 'accepted' && currentInvitation?.locationSharingConsented == null
  useEffect(() => {
    if (showSosPopup || showLocationPopup) dialogRef.current?.focus()
  }, [showSosPopup, showLocationPopup])

  return (
    <main className="sim-page">
      <div className="sim-container">
        <div className="sim-topbar">
          <span className="sim-brand">BLOODBLINK <span aria-hidden="true">/</span> BẢN ĐỒ</span>
          <span className="sim-local-pill"><Heart size={14} /> CỬA SỔ NGƯỜI DÂN · LOCAL</span>
        </div>
        <header className="sim-heading">
          <div><h1>Hồ sơ người dân</h1><p>Lời mời SOS sẽ hiện tại đây khi bệnh viện cần người hiến máu.</p></div>
          <div className="sim-icon-box"><HeartHandshake size={26} /></div>
        </header>

        <section className="card" aria-label="Hồ sơ người dân và thông báo SOS">
          <div className="sim-profile-panel">
            <div><h2 className="sim-card-title">Hồ sơ người dân</h2><p className="sim-fineprint">Một hồ sơ người dân mô phỏng duy nhất.</p></div>
            {currentInvitation && <span className="sim-profile-id">{currentInvitation.notification.donor_id}</span>}
          </div>
          {events.isError && <div className="sim-notice sim-notice-error" role="alert">Không tải được lời mời SOS: {events.error.message}</div>}
          {respond.isError && <div className="sim-notice sim-notice-error" role="alert">Không gửi được phản hồi: {respond.error.message}</div>}
          {(notificationQueries.some(query => query.isError) || responderQueries.some(query => query.isError)) && <div className="sim-notice sim-notice-error" role="alert">Không tải được thông báo SOS. Trang sẽ thử lại tự động.</div>}
          {locationError && <div className="sim-notice sim-notice-error" role="alert">{locationError}</div>}

          {events.isLoading ? <div className="sim-empty" role="status">Đang kiểm tra lời mời…</div> : !currentInvitation ? (
            <div className="sim-empty"><CircleHelp size={24} /><h2>Chưa có thông báo SOS</h2><p>Khi có lời mời phù hợp, thông báo sẽ hiện tại đây.</p></div>
          ) : currentOutcome === 'declined' ? (
            <div className="sim-notice" role="status"><Heart size={18} /><div><strong>Cảm ơn bạn đã phản hồi.</strong><br />Xin lỗi vì đã làm phiền. Thông báo này đã đóng trên hồ sơ của bạn.</div></div>
          ) : currentOutcome === 'accepted' ? (
            <div className="sim-notice sim-notice-success" role="status"><Check size={18} /><div>
              <strong>Bệnh viện đã nhận được lời đồng ý hiến máu.</strong><br />
              {currentReward?.status === 'mock_ready'
                ? 'Bệnh viện đã xác nhận hoàn tất hiến; quà mô phỏng đang chờ bạn chọn bên dưới.'
                : currentReward?.status === 'not_completed'
                  ? 'Bệnh viện ghi nhận lần hiến này chưa hoàn tất.'
                  : 'Lời đồng ý được giữ ở đây trong lúc bệnh viện xác nhận kết quả hiến.'}
              {currentInvitation.locationSharingConsented === true
                ? ' Vị trí đã được chia sẻ cho bệnh viện trong ca SOS này.'
                : currentInvitation.locationSharingConsented === false
                  ? ' Bạn không chia sẻ vị trí; lời đồng ý hiến máu vẫn được giữ.'
                  : ' Bạn có thể chọn chia sẻ vị trí riêng cho bệnh viện.'}
            </div></div>
          ) : notificationAlreadyRead ? (
            <div className="sim-empty" role="status"><h2>Thông báo SOS đã đóng</h2><p>Hồ sơ này đã phản hồi lời mời.</p></div>
          ) : null}

          {currentInvitation && currentOutcome === 'accepted' && currentInvitation.locationSharingConsented === true && (
            <div className="sim-location-actions">
              <span className="sim-fineprint">Vị trí chỉ hiển thị với bệnh viện phát SOS, tự hết hạn sau 4 giờ.</span>
              <button className="btn btn-secondary" disabled={respond.isPending} onClick={() => respond.mutate({ invitation: currentInvitation, outcome: 'accepted', shareLocation: false })}>Thu hồi chia sẻ vị trí</button>
            </div>
          )}
          {currentInvitation && currentOutcome === 'accepted' && currentInvitation.locationSharingConsented === false && (
            <div className="sim-location-actions">
              <button className="btn btn-secondary" disabled={respond.isPending} onClick={() => shareCurrentLocation(currentInvitation)}>Chia sẻ vị trí để bệnh viện điều phối đón</button>
            </div>
          )}
          {currentInvitation && currentOutcome === 'accepted' && currentReward?.status === 'mock_ready' && (
            <section className="card" role="status">
              <div className="sim-notice sim-notice-success"><Check size={18} /><div><strong>Bệnh viện đã xác nhận bạn hoàn tất hiến máu.</strong><br />Quà mô phỏng: {currentReward.proposed_amount_vnd?.toLocaleString('vi-VN') ?? '—'}đ.</div></div>
              <h3 className="sim-card-title"><Gift size={16} /> Chọn voucher mô phỏng</h3>
              <div className="sim-voucher-grid">
                <button className={`btn btn-secondary sim-voucher ${vouchers[currentInvitation.key] === 'gotit' ? 'sim-voucher-selected' : ''}`} onClick={() => setVouchers(previous => ({ ...previous, [currentInvitation.key]: 'gotit' }))}>Got It <span>· quà demo</span></button>
                <button className={`btn btn-secondary sim-voucher ${vouchers[currentInvitation.key] === 'urbox' ? 'sim-voucher-selected' : ''}`} onClick={() => setVouchers(previous => ({ ...previous, [currentInvitation.key]: 'urbox' }))}>UrBox <span>· quà demo</span></button>
              </div>
              {vouchers[currentInvitation.key] && <div className="sim-code">BB-DEMO-{vouchers[currentInvitation.key].toUpperCase()} · KHÔNG CÓ GIÁ TRỊ THANH TOÁN</div>}
              <p className="sim-fineprint">Voucher chỉ là dữ liệu minh họa, chưa kết nối Got It/UrBox.</p>
            </section>
          )}
        </section>

        {showSosPopup && currentInvitation && (
          <div className="sim-sos-backdrop">
            <section ref={dialogRef} tabIndex={-1} className="sim-sos-dialog" role="alertdialog" aria-modal="true" aria-labelledby="sim-sos-title" aria-describedby="sim-sos-description">
              <div className="sim-tag"><Radio size={13} /> THÔNG BÁO SOS</div>
              <h2 id="sim-sos-title">Bệnh viện đang cần người hiến {currentInvitation.event.abo ?? ''}{currentInvitation.event.rh ?? ''}</h2>
              <p id="sim-sos-description">{currentInvitation.event.component_code ?? 'Máu'} · Mã ca {currentInvitation.event.id}</p>
              <div className="sim-offer-actions">
                <button className="btn sim-button-accept" disabled={respond.isPending} onClick={() => respond.mutate({ invitation: currentInvitation, outcome: 'accepted' })}><Check size={16} /> {respond.isPending ? 'Đang gửi…' : 'Tôi đồng ý hiến máu'}</button>
                <button className="btn btn-secondary" disabled={respond.isPending} onClick={() => respond.mutate({ invitation: currentInvitation, outcome: 'declined' })}><X size={16} /> Lần này tôi không thể</button>
              </div>
            </section>
          </div>
        )}
        {showLocationPopup && currentInvitation && (
          <div className="sim-sos-backdrop">
            <section ref={dialogRef} tabIndex={-1} className="sim-sos-dialog" role="dialog" aria-modal="true" aria-labelledby="sim-location-title" aria-describedby="sim-location-description">
              <div className="sim-tag"><MapPin size={13} /> CHIA SẺ VỊ TRÍ · TÙY CHỌN</div>
              <h2 id="sim-location-title">Bạn có muốn chia sẻ vị trí hiện tại?</h2>
              <p id="sim-location-description">Vị trí GPS chỉ gửi cho bệnh viện phát SOS để vẽ đường đón. Bệnh viện khác không xem được; dữ liệu tự hết hạn sau 4 giờ và có thể thu hồi bất cứ lúc nào.</p>
              <div className="sim-offer-actions">
                <button className="btn sim-button-accept" disabled={respond.isPending} onClick={() => shareCurrentLocation(currentInvitation)}><MapPin size={16} /> Chia sẻ vị trí</button>
                <button className="btn btn-secondary" disabled={respond.isPending} onClick={() => respond.mutate({ invitation: currentInvitation, outcome: 'accepted', shareLocation: false })}>Không chia sẻ</button>
              </div>
            </section>
          </div>
        )}
      </div>
    </main>
  )
}
