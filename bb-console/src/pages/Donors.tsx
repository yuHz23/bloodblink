import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, ShieldCheck, ShieldOff, Siren, MapPin, Globe2 } from 'lucide-react'
import { api, type NearbyDonor } from '../lib/api'
import { useAuth } from '../lib/auth'
import { COMPONENT_LABELS } from '../lib/constants'

/**
 * Tìm người hiến cùng nhóm máu quanh một cơ sở y tế.
 *
 * Đây là mảnh mà trước P1 hoàn toàn không có: bảng `donor` chỉ có dữ liệu mẫu,
 * và không màn hình nào của cơ sở y tế tra được ai đang ở gần.
 *
 * Quyền riêng tư giữ nguyên: kết quả chỉ có MÃ người hiến, nhóm máu và điều
 * kiện hiến. Không họ tên, không số điện thoại, không toạ độ — chỉ ô lưới H3
 * (~1.2 km) và ô đó tự hết hạn sau TTL.
 */

const RINGS = [
  { ring: 0, label: 'Vòng 0', scope: '~1 km · cùng nhóm máu', time: 'T+0', color: '#3b82f6' },
  { ring: 1, label: 'Vòng 1', scope: '~3 km · nhóm tương hợp', time: 'T+10 phút', color: '#f59e0b' },
  { ring: 2, label: 'Vòng 2', scope: '~5 km · mở rộng', time: 'T+25 phút', color: '#ef4444' },
  { ring: 3, label: 'Vòng 3', scope: 'Toàn thành phố', time: 'T+45 phút', color: '#7c3aed' },
]

const ABO_OPTIONS = ['O', 'A', 'B', 'AB']

export default function Donors() {
  const qc = useQueryClient()
  const { session } = useAuth()

  const [facilityId, setFacilityId] = useState('')
  const [abo, setAbo] = useState('O')
  const [rh, setRh] = useState('+')
  const [component, setComponent] = useState('WB')
  const [ring, setRing] = useState(0)
  const [eligibleOnly, setEligibleOnly] = useState(true)
  const [includeUnverified, setIncludeUnverified] = useState(false)
  const [sosMessage, setSosMessage] = useState<string | null>(null)

  const { data: facilities } = useQuery({
    queryKey: ['facilities'],
    queryFn: () => api.listFacilities(),
  })

  // Mặc định chọn cơ sở gắn với tài khoản đang đăng nhập.
  const activeFacility = useMemo(() => {
    if (!facilities?.length) return undefined
    const wanted = facilityId || session?.facilityId || facilities[0].id
    return facilities.find(f => f.id === wanted) ?? facilities[0]
  }, [facilities, facilityId, session])

  const h3Cell = activeFacility?.h3_cell ?? null

  const { data: result, isFetching, error, refetch } = useQuery({
    queryKey: ['nearby', h3Cell, abo, rh, component, ring, eligibleOnly, includeUnverified],
    queryFn: () => api.findNearbyDonors({
      h3Cell: h3Cell!,
      abo, rh,
      componentCode: component,
      ring,
      eligibleOnly,
      verifiedOnly: !includeUnverified,
      limit: 100,
    }),
    enabled: !!h3Cell,
  })

  const verify = useMutation({
    mutationFn: ({ id, verified }: { id: string; verified: boolean }) =>
      api.verifyDonor(id, verified, session?.facilityId ?? session?.username ?? undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['nearby'] }),
  })

  const openSos = useMutation({
    mutationFn: () => api.createSosEvent({
      facility_id: activeFacility?.id,
      component_code: component,
      abo, rh,
      urgency: 'emergency',
      qty: 1,
      ring,
      h3_cell: h3Cell ?? undefined,
    }),
    onSuccess: (ev) => setSosMessage(ev.message),
  })

  return (
    <>
      <h2>Tìm người hiến máu</h2>
      <p className="subtitle">
        Tra theo nhóm máu quanh ô lưới H3 của cơ sở · Kết quả ẩn danh, không toạ độ
      </p>

      {/* Bộ lọc */}
      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Cơ sở y tế</label>
            <select value={activeFacility?.id ?? ''} onChange={e => setFacilityId(e.target.value)}>
              {facilities?.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Nhóm máu người bệnh</label>
            <select value={abo} onChange={e => setAbo(e.target.value)}>
              {ABO_OPTIONS.map(g => <option key={g} value={g}>Nhóm {g}</option>)}
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>RhD</label>
            <select value={rh} onChange={e => setRh(e.target.value)}>
              <option value="+">RhD⁺</option>
              <option value="-">RhD⁻ (hiếm, ~0,1%)</option>
            </select>
          </div>

          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Chế phẩm cần</label>
            <select value={component} onChange={e => setComponent(e.target.value)}>
              {Object.entries(COMPONENT_LABELS).map(([code, label]) =>
                <option key={code} value={code}>{label}</option>)}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 16, fontSize: 13 }}>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input type="checkbox" checked={eligibleOnly}
                   onChange={e => setEligibleOnly(e.target.checked)} />
            Chỉ người đủ khoảng cách hiến (Điều 6)
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input type="checkbox" checked={includeUnverified}
                   onChange={e => setIncludeUnverified(e.target.checked)} />
            Hiện cả người chưa xác minh
          </label>
          <button className="btn btn-secondary" onClick={() => refetch()} disabled={!h3Cell}>
            <Search size={15} /> Tìm lại
          </button>
        </div>

        {h3Cell && (
          <div style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 12,
                        display: 'flex', gap: 6, alignItems: 'center' }}>
            <MapPin size={13} />
            Tâm tìm kiếm: ô lưới <code style={{ fontFamily: 'var(--font-mono)' }}>{h3Cell}</code>
            {' '}(suy ra từ toạ độ cơ sở, không lưu toạ độ người hiến)
          </div>
        )}
      </div>

      {/* Chọn vòng */}
      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Vòng huy động</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {RINGS.map(r => {
            const active = r.ring === ring
            return (
              <div key={r.ring} onClick={() => setRing(r.ring)} style={{
                background: active ? `${r.color}15` : 'var(--bb-gray-50)',
                border: `2px solid ${active ? r.color : 'var(--bb-gray-200)'}`,
                borderRadius: 10, padding: '12px 10px', textAlign: 'center', cursor: 'pointer',
              }}>
                <div style={{ fontSize: 24, fontWeight: 800, color: r.color }}>{r.ring}</div>
                <div style={{ fontSize: 11, fontWeight: 600, color: r.color }}>{r.time}</div>
                <div style={{ fontSize: 11, color: 'var(--bb-gray-600)', marginTop: 4 }}>{r.scope}</div>
              </div>
            )
          })}
        </div>
        <p style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 10 }}>
          Vòng 0 chỉ gọi người <strong>cùng nhóm máu</strong>. Từ vòng 1 mới mở sang nhóm tương hợp;
          vòng 3 bỏ ràng buộc vị trí.
        </p>
      </div>

      {/* Kết quả */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3>
            Kết quả{' '}
            {result && (
              <span style={{ fontWeight: 500, color: 'var(--bb-gray-500)', fontSize: 14 }}>
                — {result.total_donors} người hiến
                {result.citywide
                  ? ' (toàn thành phố)'
                  : ` trong ${result.cells_searched?.length ?? 0} ô lưới`}
              </span>
            )}
          </h3>
          <button className="btn btn-danger" disabled={!h3Cell || openSos.isPending}
                  onClick={() => openSos.mutate()}>
            <Siren size={15} /> {openSos.isPending ? 'Đang mở…' : 'Mở lời kêu gọi SOS'}
          </button>
        </div>

        {sosMessage && (
          <div style={{ background: '#fef3c7', color: '#92400e', borderRadius: 8,
                        padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
            {sosMessage}
          </div>
        )}

        {error && (
          <div style={{ background: '#fee2e2', color: '#b91c1c', borderRadius: 8,
                        padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
            {error instanceof Error ? error.message : 'Lỗi tìm kiếm'}
          </div>
        )}

        {isFetching && <p style={{ color: 'var(--bb-gray-500)' }}>Đang tìm…</p>}

        {result && result.donors.length === 0 && !isFetching && (
          <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--bb-gray-500)' }}>
            <Globe2 size={28} style={{ opacity: 0.4 }} />
            <p style={{ marginTop: 8, fontSize: 14 }}>
              Không có người hiến {abo}{rh} nào đủ điều kiện trong phạm vi này.
            </p>
            {ring < 3 && (
              <button className="btn btn-secondary" style={{ marginTop: 10 }}
                      onClick={() => setRing(ring + 1)}>
                Leo thang lên vòng {ring + 1}
              </button>
            )}
          </div>
        )}

        {result && result.donors.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Mã người hiến</th>
                  <th>Nhóm máu</th>
                  <th>Điều kiện hiến</th>
                  <th>Lần hiến gần nhất</th>
                  <th>Xác minh</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {result.donors.map((d: NearbyDonor) => (
                  <tr key={d.donor_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{d.donor_id}</td>
                    <td style={{ fontWeight: 700 }}>{d.blood_type}</td>
                    <td>
                      {d.eligible
                        ? <span className="badge badge-normal">Đủ điều kiện</span>
                        : <span className="badge badge-warning" title={d.ineligible_reason ?? ''}>
                            Chưa đủ
                          </span>}
                    </td>
                    <td style={{ fontSize: 13, color: 'var(--bb-gray-600)' }}>
                      {d.days_since_donation === null
                        ? 'Chưa có dữ liệu'
                        : `${d.days_since_donation} ngày trước`}
                    </td>
                    <td>
                      {d.verified
                        ? <span className="badge badge-normal">Đã xác minh</span>
                        : <span className="badge badge-warning">Chờ xác minh</span>}
                    </td>
                    <td>
                      <button
                        className="btn btn-secondary"
                        disabled={verify.isPending}
                        onClick={() => verify.mutate({ id: d.donor_id, verified: !d.verified })}
                      >
                        {d.verified
                          ? <><ShieldOff size={14} /> Thu hồi</>
                          : <><ShieldCheck size={14} /> Xác minh</>}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p style={{ fontSize: 12, color: 'var(--bb-gray-400)', marginTop: 14, lineHeight: 1.7 }}>
          Danh sách chỉ hiện mã người hiến — máy chủ không lưu họ tên, số điện thoại hay toạ độ.
          Người hiến chưa được cơ sở y tế xác minh sẽ không xuất hiện trong tìm kiếm mặc định.
        </p>
      </div>
    </>
  )
}
