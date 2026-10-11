import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, CircleCheck, CircleX, Clock3, Droplets, Search, ShieldCheck } from 'lucide-react'
import { api, type TransferOffer } from '../../lib/api'
import { COMPONENT_SHORT } from '../../lib/constants'
import { useAuth } from '../../lib/auth'

function offerStatus(offer: TransferOffer) {
  if (offer.status === 'pending') return 'Đang chờ phản hồi'
  if (offer.status === 'accepted') return `Đã nhận ${offer.accepted_qty} đơn vị`
  if (offer.status === 'declined') return 'Đã từ chối'
  if (offer.status === 'expired') return 'Đã hết hạn'
  if (offer.status === 'cancelled') return 'Đã đủ số lượng'
  return 'Không có nguồn'
}

export default function Theme1Inbox() {
  const { session } = useAuth()
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [search, setSearch] = useState('')
  const [quantities, setQuantities] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState<{ text: string; accepted: boolean } | null>(null)
  const health = useQuery({ queryKey: ['theme1-inbox-health'], queryFn: api.health, refetchInterval: 15_000 })
  const offers = useQuery({ queryKey: ['theme1-incoming-offers'], queryFn: () => api.listIncomingTransferOffers(session?.facilityId ?? undefined), refetchInterval: 2_000, refetchIntervalInBackground: true })
  const quantitySelectionSupported = health.data?.capabilities?.transfer_offer_quantity === true
  const filteredOffers = useMemo(() => (offers.data ?? []).filter(offer => `${offer.requester_facility_name} ${offer.abo ?? ''}${offer.rh ?? ''} ${offer.component_code}`.toLowerCase().includes(search.toLowerCase())), [offers.data, search])
  const selected = filteredOffers.find(offer => offer.id === selectedId) ?? filteredOffers.find(offer => offer.status === 'pending') ?? filteredOffers[0]
  const selectedQuantity = selected ? Number(quantities[selected.id] ?? selected.offered_qty) : 0
  const validQuantity = !!selected && Number.isInteger(selectedQuantity) && selectedQuantity > 0 && selectedQuantity <= selected.offered_qty
  const respond = useMutation({
    mutationFn: ({ offer, accept }: { offer: TransferOffer; accept: boolean }) => api.respondToTransferOffer(
      offer.id,
      accept,
      offer.source_facility_id ?? session?.facilityId ?? undefined,
      accept ? selectedQuantity : undefined,
    ),
    onSuccess: async (_result, variables) => {
      setNotice({ accepted: variables.accept, text: variables.accept ? `Đã chấp nhận điều chuyển ${selectedQuantity} đơn vị.` : 'Đã từ chối yêu cầu điều chuyển.' })
      setSelectedId('')
      await Promise.all([
        client.invalidateQueries({ queryKey: ['theme1-incoming-offers'] }),
        client.invalidateQueries({ queryKey: ['map-transfer-offers'] }),
        client.invalidateQueries({ queryKey: ['stock-by-facility'] }),
      ])
    },
  })

  return <>
    <div className="theme1-page-heading"><div><span className="theme1-eyebrow"><Building2 size={13} /> Kênh hỗ trợ liên viện</span><h2>Yêu cầu điều chuyển</h2><p>Các bệnh viện cần hỗ trợ chế phẩm máu trong mạng lưới BLOOD-BLINK SOS.</p></div><span className="theme1-status-pill"><i /> {offers.data?.filter(offer => offer.status === 'pending').length ?? 0} yêu cầu đang chờ</span></div>
    <div className="theme1-inbox-toolbar"><label className="theme1-search"><Search size={17} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Tìm bệnh viện, nhóm máu, chế phẩm…" /></label><span className="theme1-inbox-facility"><ShieldCheck size={16} /> {session?.facilityName ?? 'Trung tâm điều phối'}</span></div>
    {notice && <div className={`theme1-inbox-notice${notice.accepted ? ' is-success' : ''}`} role="status">{notice.accepted ? <CircleCheck size={18} /> : <CircleX size={18} />}{notice.text}<button type="button" onClick={() => setNotice(null)} aria-label="Đóng thông báo">×</button></div>}
    {respond.error && <div className="theme1-inbox-notice" role="alert"><CircleX size={18} />{respond.error.message}</div>}

    <div className="theme1-inbox-layout">
      <section className="theme1-inbox-list" aria-label="Danh sách yêu cầu">
        <div className="theme1-list-heading"><strong>Hộp thư đến</strong><span>{filteredOffers.length}</span></div>
        {offers.isLoading ? <div className="theme1-empty" role="status">Đang tải yêu cầu…</div> : filteredOffers.length ? filteredOffers.map(offer => <button type="button" className={`theme1-offer-row${selected?.id === offer.id ? ' is-selected' : ''}${offer.urgency === 'emergency' ? ' is-urgent' : ''}`} onClick={() => setSelectedId(offer.id)} key={offer.id}>
          <span className={`theme1-offer-priority${offer.urgency === 'emergency' ? ' is-emergency' : ''}`}>{offer.urgency === 'emergency' ? 'KHẨN CẤP' : offer.urgency === 'urgent' ? 'ƯU TIÊN' : 'BÌNH THƯỜNG'}</span><time>{new Date(offer.created_at).toLocaleString('vi-VN', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })}</time>
          <strong>{offer.requester_facility_name}</strong><span className="theme1-offer-summary">{offer.abo}{offer.rh} <i /> {COMPONENT_SHORT[offer.component_code] ?? offer.component_code} <i /> {offer.qty} đơn vị</span>
          <small><Clock3 size={13} /> Phản hồi trước {new Date(offer.expires_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</small>
        </button>) : <div className="theme1-empty">{search ? 'Không tìm thấy yêu cầu phù hợp.' : 'Chưa có yêu cầu điều chuyển mới.'}</div>}
      </section>

      <section className="theme1-panel theme1-offer-detail" aria-label="Chi tiết yêu cầu điều chuyển">
        {selected ? <>
          <div className="theme1-offer-detail-head"><div><span className={`theme1-offer-priority${selected.urgency === 'emergency' ? ' is-emergency' : ''}`}>{selected.urgency === 'emergency' ? 'KHẨN CẤP' : selected.urgency === 'urgent' ? 'ƯU TIÊN' : 'BÌNH THƯỜNG'}</span><h3>{selected.requester_facility_name}</h3><p>{selected.requester_facility_id} <i /> Trong mạng lưới BLOOD-BLINK SOS</p></div><div className="theme1-offer-deadline"><Clock3 size={19} /><strong>{selected.status === 'pending' ? `Còn ${Math.max(0, Math.ceil((Date.parse(selected.expires_at) - Date.now()) / 3_600_000))} giờ` : offerStatus(selected)}</strong><small>Hạn {new Date(selected.expires_at).toLocaleString('vi-VN')}</small></div></div>
          <div className="theme1-detail-card"><h4><Droplets size={17} /> Nội dung yêu cầu</h4><div className="theme1-request-metrics"><div><small>Nhóm máu</small><strong className="theme1-detail-blood">{selected.abo}{selected.rh}</strong></div><div><small>Chế phẩm máu</small><strong>{COMPONENT_SHORT[selected.component_code] ?? selected.component_code}</strong><span>{selected.component_code}</span></div><div><small>Số lượng yêu cầu</small><strong className="theme1-detail-quantity">{selected.qty} <small>đơn vị</small></strong></div></div></div>
          <div className="theme1-detail-card theme1-stock-response"><h4><WarehouseIcon /> Khả năng đáp ứng</h4><div className="theme1-response-stock"><strong>{selected.available_qty}</strong><span>đơn vị có thể chia sẻ an toàn</span><i><b style={{ width: `${selected.qty ? Math.min(100, selected.available_qty / selected.qty * 100) : 0}%` }} /></i><small>Đề nghị điều chuyển tối đa {selected.offered_qty} đơn vị</small></div>
            {selected.status === 'pending' && <label className="theme1-quantity-label">Số lượng đồng ý điều chuyển<div><input type="number" min={1} max={selected.offered_qty} step={1} value={quantities[selected.id] ?? String(selected.offered_qty)} onChange={event => setQuantities(current => ({ ...current, [selected.id]: event.target.value }))} /><span>đơn vị</span></div></label>}
          </div>
          {selected.status === 'pending' ? <div className="theme1-response-actions"><button className="btn btn-primary" disabled={respond.isPending || !validQuantity || !quantitySelectionSupported} onClick={() => respond.mutate({ offer: selected, accept: true })}><CircleCheck size={17} />{respond.isPending ? 'Đang gửi…' : 'Chấp nhận hỗ trợ'}</button><button className="btn btn-secondary" disabled={respond.isPending} onClick={() => respond.mutate({ offer: selected, accept: false })}><CircleX size={17} />Từ chối</button>{!quantitySelectionSupported && <small>BB-Core hiện tại chưa bật chọn số lượng xác nhận.</small>}</div> : <div className="theme1-inbox-notice is-success" role="status"><CircleCheck size={18} />{offerStatus(selected)}</div>}
          <div className="theme1-response-history"><span className="theme1-history-dot" /><div><time>{new Date(selected.created_at).toLocaleString('vi-VN')}</time><strong>Đã tiếp nhận yêu cầu</strong><small>Đang chờ bệnh viện phản hồi</small></div></div>
        </> : <div className="theme1-empty theme1-inbox-empty"><Building2 size={25} /><strong>Chọn một yêu cầu để xem chi tiết</strong><span>Nội dung và khả năng đáp ứng sẽ hiển thị tại đây.</span></div>}
      </section>
    </div>
    <p className="theme1-inbox-footnote">Phản hồi tại đây được đồng bộ với bản đồ điều phối và tồn kho của cơ sở.</p>
  </>
}

function WarehouseIcon() {
  return <Building2 size={17} aria-hidden="true" />
}
