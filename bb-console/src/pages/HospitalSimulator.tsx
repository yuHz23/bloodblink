import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BadgeCheck, Building2, CircleCheck, CircleX, MapPin, RefreshCw } from 'lucide-react'
import { api, type TransferOffer } from '../lib/api'
import './Simulation.css'

function stockClass(count: number) {
  return count < 20 ? 'sim-stock-red' : count < 60 ? 'sim-stock-yellow' : 'sim-stock-green'
}

function stockText(count: number) {
  return count < 20 ? 'Tồn kho đỏ · rất thấp' : count < 60 ? 'Tồn kho vàng · thấp' : 'Tồn kho an toàn'
}

export default function HospitalSimulator() {
  const client = useQueryClient()
  const [notice, setNotice] = useState<{ text: string; accepted: boolean } | null>(null)
  const [honorPoints, setHonorPoints] = useState(0)
  const facilities = useQuery({ queryKey: ['sim-facilities'], queryFn: api.listFacilities })
  const offers = useQuery({
    queryKey: ['sim-hospital-offers'],
    queryFn: () => api.listIncomingTransferOffers(),
    refetchInterval: 2000,
  })

  const respond = useMutation({
    mutationFn: ({ offer, accept }: { offer: TransferOffer; accept: boolean }) =>
      api.respondToTransferOffer(offer.id, accept, offer.source_facility_id ?? undefined),
    onSuccess: async (result, variables) => {
      if (variables.accept) {
        setHonorPoints(points => points + Math.max(1, result.accepted_qty) * 100)
        setNotice({ text: `Đã nhận hỗ trợ ${result.accepted_qty} đơn vị. Điểm vinh danh demo đã được cộng.`, accepted: true })
      } else {
        setNotice({ text: 'Đã từ chối yêu cầu. Hệ thống sẽ tiếp tục hỏi các bệnh viện còn lại.', accepted: false })
      }
      await client.invalidateQueries({ queryKey: ['sim-hospital-offers'] })
      await client.invalidateQueries({ queryKey: ['map-transfer-offers'] })
      await client.invalidateQueries({ queryKey: ['stock-by-facility'] })
    },
  })

  const pendingOffers = offers.data ?? []
  const offersByFacility = useMemo(() => {
    const grouped = new Map<string, TransferOffer[]>()
    for (const offer of pendingOffers) {
      const items = grouped.get(offer.source_facility_id ?? '') ?? []
      items.push(offer)
      grouped.set(offer.source_facility_id ?? '', items)
    }
    return grouped
  }, [pendingOffers])

  return (
    <main className="sim-page">
      <div className="sim-container">
        <div className="sim-topbar">
          <a className="sim-brand" href="http://127.0.0.1:5174/map">BLOODBLINK <span aria-hidden="true">/</span> BẢN ĐỒ</a>
          <span className="sim-local-pill"><Building2 size={14} /> CỬA SỔ BỆNH VIỆN · LOCAL</span>
        </div>

        <header className="sim-heading">
          <div>
            <div className="sim-tag"><MapPin size={13} /> Mô phỏng điều chuyển trên bản đồ</div>
            <h1>Hộp thư điều chuyển</h1>
            <p>Tất cả bệnh viện cùng hiển thị để bạn thử chấp nhận hoặc từ chối ngay.</p>
          </div>
          <div className="sim-icon-box"><Building2 size={26} /></div>
        </header>

        <section className="card sim-controls" aria-label="Làm mới yêu cầu">
          <div><strong>{facilities.data?.length ?? 0}</strong> bệnh viện đang theo dõi · cập nhật tự động mỗi 2 giây</div>
          <button className="btn btn-secondary" onClick={() => offers.refetch()} disabled={offers.isFetching}>
            <RefreshCw size={15} /> Làm mới
          </button>
        </section>

        <section className="sim-metrics" aria-label="Tổng quan">
          <div className="sim-metric"><strong>{facilities.data?.length ?? 0}</strong><span>Bệnh viện hiển thị</span></div>
          <div className="sim-metric"><strong>{pendingOffers.length}</strong><span>Yêu cầu đang chờ</span></div>
          <div className="sim-metric"><strong>{honorPoints}</strong><span>Điểm vinh danh mô phỏng</span></div>
        </section>

        {respond.isSuccess && notice && (
          <div className={`sim-notice ${notice.accepted ? 'sim-notice-success' : ''}`} role="status">
            {notice.accepted ? <BadgeCheck size={18} /> : <CircleX size={18} />}
            <div><strong>{notice.accepted ? 'Được ghi nhận hỗ trợ' : 'Đã ghi nhận phản hồi'}</strong><br />{notice.text}</div>
          </div>
        )}
        {respond.isError && <div className="sim-notice sim-notice-error" role="alert">{respond.error.message}</div>}
        {facilities.isError && <div className="sim-notice sim-notice-error" role="alert">Không tải được danh sách bệnh viện: {facilities.error.message}</div>}
        {offers.isError && <div className="sim-notice sim-notice-error" role="alert">Không tải được tín hiệu điều chuyển: {offers.error.message}</div>}

        {offers.isLoading || facilities.isLoading ? <div className="card sim-empty" role="status">Đang tải danh sách bệnh viện…</div> : (
          <section className="sim-offer-list" aria-label="Tất cả bệnh viện và yêu cầu điều chuyển">
            {(facilities.data ?? []).map(facility => {
              const facilityOffers = offersByFacility.get(facility.id) ?? []
              return (
                <article className="sim-offer" key={facility.id}>
                  <div className="sim-offer-head">
                    <div><h2>{facility.name}</h2><p>{facility.tier} · {facilityOffers.length ? `${facilityOffers.length} yêu cầu đang chờ` : 'Chưa có yêu cầu mới'}</p></div>
                    {facilityOffers.length > 0 && <span className={`sim-tag ${stockClass(Math.min(...facilityOffers.map(offer => offer.available_qty)))}`}>
                      {stockText(Math.min(...facilityOffers.map(offer => offer.available_qty)))}
                    </span>}
                  </div>
                  {facilityOffers.length === 0 ? <p className="sim-fineprint">Yêu cầu điều chuyển gửi đến bệnh viện này sẽ xuất hiện tại đây.</p> : facilityOffers.map(offer => (
                    <div key={offer.id} style={{ borderTop: '1px solid var(--border-color, #ddd)', paddingTop: 12, marginTop: 12 }}>
                      <div className="sim-offer-meta">
                        <span><strong>{offer.abo}{offer.rh}</strong> · {offer.component_code}</span>
                        <span>{offer.requester_facility_name} cần <strong>{offer.offered_qty}</strong> / {offer.qty} đơn vị</span>
                        <span>Kho chia sẻ: <strong>{offer.available_qty}</strong> đơn vị</span>
                        <span>Hạn trả lời: {new Date(offer.expires_at).toLocaleTimeString('vi-VN')}</span>
                      </div>
                      <div className="sim-offer-actions">
                        <button className="btn sim-button-accept" disabled={respond.isPending} onClick={() => respond.mutate({ offer, accept: true })}>
                          <CircleCheck size={16} /> {respond.isPending ? 'Đang gửi…' : 'Chấp nhận hỗ trợ'}
                        </button>
                        <button className="btn btn-secondary" disabled={respond.isPending} onClick={() => respond.mutate({ offer, accept: false })}>
                          <CircleX size={16} /> Từ chối
                        </button>
                      </div>
                    </div>
                  ))}
                </article>
              )
            })}
          </section>
        )}

        <footer className="sim-footer">
          <span>Phản hồi tại đây cập nhật chung với bản đồ điều phối.</span>
          <a href="http://127.0.0.1:5174/map" target="_blank" rel="noreferrer">Mở bản đồ điều phối ↗</a>
          <span>Điểm vinh danh chỉ là dữ liệu demo, chưa có thưởng thật.</span>
        </footer>
      </div>
    </main>
  )
}
