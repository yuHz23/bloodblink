import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { URGENCY_LABELS, urgencyBadge } from '../lib/constants'
import { Search, AlertTriangle } from 'lucide-react'

export default function Matching() {
  const qc = useQueryClient()
  const [step, setStep] = useState<'request' | 'results'>('request')
  const [requestId, setRequestId] = useState<string | null>(null)

  // Form state
  const [formData, setFormData] = useState({
    requester_facility_id: 'fac-bv-tmhh',
    component_code: 'PLT',
    abo: '',
    rh: '',
    qty: 1,
    urgency: 'routine',
    needed_by: new Date(Date.now() + 6 * 3600000).toISOString().slice(0, 16),
    recipient_sex: '',
    recipient_age: '',
  })

  // Create request mutation
  const createRequest = useMutation({
    mutationFn: (data: typeof formData) => api.createTransferRequest({
      ...data,
      abo: data.abo || undefined,
      rh: data.rh || undefined,
      recipient_sex: data.recipient_sex || undefined,
      recipient_age: data.recipient_age ? Number(data.recipient_age) : undefined,
    }),
    onSuccess: (result) => {
      setRequestId(result.id)
      setStep('results')
      qc.invalidateQueries({ queryKey: ['match-results'] })
    },
  })

  // Tên cơ sở, để khuyến nghị nói "BV Chợ Rẫy" chứ không phải "fac-bv-cho-ray".
  const { data: facilities } = useQuery({
    queryKey: ['facilities'],
    queryFn: () => api.listFacilities(),
  })

  // Find matches
  const { data: matchResults, isLoading: matching } = useQuery({
    queryKey: ['match-results', requestId],
    queryFn: () => api.findMatches(requestId!),
    enabled: !!requestId && step === 'results',
  })

  // Mở lời kêu gọi ngay từ màn kết quả ghép nguồn.
  //
  // Trước đây nhân viên tìm nguồn xong, thấy thiếu, rồi phải TỰ NHỚ sang mục SOS
  // và tự điền lại nhóm máu, chế phẩm, cơ sở — bước dễ rơi nhất đúng lúc đang
  // cuống. Máy chủ đã tính sẵn mức khẩn và vòng bắt đầu (xem sos_advice.py),
  // ở đây chỉ việc chuyển tiếp.
  const [sosOpened, setSosOpened] = useState<string | null>(null)
  const openSos = useMutation({
    mutationFn: () => api.createSosEvent({
      facility_id: formData.requester_facility_id,
      component_code: formData.component_code,
      abo: formData.abo || undefined,
      rh: formData.rh || undefined,
      urgency: matchResults?.sos_urgency ?? formData.urgency,
      qty: matchResults?.sos_target_count || 1,
      ring: matchResults?.sos_start_ring ?? 0,
    }),
    onSuccess: (ev) => setSosOpened(ev.message || 'Đã mở lời kêu gọi'),
  })

  // Approve mutation
  const approveRequest = useMutation({
    mutationFn: ({ reqId, approvedBy }: { reqId: string; approvedBy: string }) =>
      api.approveTransfer(reqId, approvedBy),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-results'] })
    },
  })

  const uBadge = urgencyBadge(formData.urgency)

  return (
    <>
      <h2>Ghép nguồn & điều chuyển</h2>
      <p className="subtitle">Tìm chế phẩm tương hợp, xếp hạng có giải thích, sinh lệnh vận chuyển — dưới 60 giây</p>

      {step === 'request' && (
        <div className="card" style={{ maxWidth: 600 }}>
          <h3 style={{ marginBottom: 16 }}>Tạo yêu cầu điều chuyển</h3>

          <div className="form-group">
            <label>Loại chế phẩm</label>
            <select value={formData.component_code} onChange={e => setFormData({...formData, component_code: e.target.value})}>
              <option value="RBC">Hồng cầu (RBC)</option>
              <option value="PLT">Tiểu cầu (PLT)</option>
              <option value="FFP">Huyết tương (FFP)</option>
            </select>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label>Nhóm máu ABO (để trống = bất kỳ)</label>
              <select value={formData.abo} onChange={e => setFormData({...formData, abo: e.target.value})}>
                <option value="">Bất kỳ (tương hợp)</option>
                <option value="O">O</option>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="AB">AB</option>
              </select>
            </div>
            <div className="form-group">
              <label>RhD</label>
              <select value={formData.rh} onChange={e => setFormData({...formData, rh: e.target.value})}>
                <option value="">Bất kỳ</option>
                <option value="+">RhD⁺</option>
                <option value="-">RhD⁻</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label>Số lượng</label>
              <input type="number" min={1} max={10} value={formData.qty}
                onChange={e => setFormData({...formData, qty: Number(e.target.value)})} />
            </div>
            <div className="form-group">
              <label>Mức khẩn cấp</label>
              <select value={formData.urgency} onChange={e => setFormData({...formData, urgency: e.target.value})}>
                <option value="routine">Luân chuyển (0–6h)</option>
                <option value="urgent">Cấp bách (2–6h)</option>
                <option value="emergency">Cấp cứu (dưới 2h)</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label>Thời gian cần trước</label>
            <input type="datetime-local" value={formData.needed_by}
              onChange={e => setFormData({...formData, needed_by: e.target.value})} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label>Giới tính người nhận (cho RhD)</label>
              <select value={formData.recipient_sex} onChange={e => setFormData({...formData, recipient_sex: e.target.value})}>
                <option value="">Không xác định</option>
                <option value="M">Nam</option>
                <option value="F">Nữ</option>
              </select>
            </div>
            <div className="form-group">
              <label>Tuổi người nhận</label>
              <input type="number" min={0} max={120} placeholder="Tuổi"
                value={formData.recipient_age} onChange={e => setFormData({...formData, recipient_age: e.target.value})} />
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8, padding: '10px 14px', background: uBadge.bg, borderRadius: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: uBadge.text, textTransform: 'uppercase', letterSpacing: 0.06 }}>
              {URGENCY_LABELS[formData.urgency]?.label}
            </span>
            <span style={{ fontSize: 12, color: 'var(--bb-gray-600)' }}>
              {URGENCY_LABELS[formData.urgency]?.desc}
            </span>
          </div>

          <button className="btn btn-primary" style={{ marginTop: 20 }}
            onClick={() => createRequest.mutate(formData)} disabled={createRequest.isPending}>
            <Search size={16} />
            {createRequest.isPending ? 'Đang tìm...' : 'Tìm nguồn tương hợp'}
          </button>

          {formData.recipient_sex === 'F' && Number(formData.recipient_age) >= 18 && Number(formData.recipient_age) <= 45 && formData.rh === '-' && (
            <div style={{ marginTop: 12, padding: '10px 14px', background: 'var(--bb-red-soft)', borderRadius: 6, fontSize: 13 }}>
              <AlertTriangle size={14} style={{ verticalAlign: -2, color: 'var(--bb-red)' }} />
              {' '}<strong>Ràng buộc chuyên môn:</strong> Không hạ chuẩn RhD cho phụ nữ tuổi sinh đẻ (18–45) — rủi ro bệnh tan máu ở thai nhi.
            </div>
          )}
        </div>
      )}

      {step === 'results' && (
        <>
          {matching && (
            <div className="card" style={{ textAlign: 'center', padding: 40 }}>
              <div style={{ fontSize: 14, color: 'var(--bb-gray-500)' }}>Đang ghép nguồn và xếp hạng...</div>
            </div>
          )}

          {matchResults && (
            <>
              <div className="stat-grid">
                <div className="stat-card">
                  <div className="stat-number">{matchResults.total_candidates}</div>
                  <div className="stat-label">Tổng đơn vị kiểm</div>
                </div>
                <div className="stat-card">
                  <div className="stat-number" style={{ color: 'var(--bb-green)' }}>{matchResults.compatible_count}</div>
                  <div className="stat-label">Tương hợp</div>
                </div>
                <div className="stat-card">
                  <div className="stat-number" style={{ color: 'var(--bb-red)' }}>
                    {matchResults.total_candidates - matchResults.compatible_count}
                  </div>
                  <div className="stat-label">Loại (không tương hợp)</div>
                </div>
              </div>

              {matchResults.sos_action && matchResults.sos_action !== 'not_needed' && (
                <div className="card sos-advice" data-action={matchResults.sos_action}>
                  <div className="sos-advice-head">
                    {matchResults.sos_action === 'required'
                      ? 'Kho không đủ — cần huy động người hiến'
                      : 'Kho đủ lần này, nhưng nên mở lời kêu gọi để bù'}
                  </div>
                  <p className="sos-advice-why">{matchResults.sos_reason}</p>

                  {/* Nói thẳng giới hạn: gọi người KHÔNG cứu kịp ca đang cấp cứu.
                      Giấu điều này đi là để người điều phối chờ một thứ không tới. */}
                  {matchResults.sos_action === 'required' && formData.urgency === 'emergency' && (
                    <p className="sos-advice-warn">
                      Lưu ý: máu vừa lấy phải qua sàng lọc, tách chế phẩm và hoà hợp
                      (Điều 14–15 TT 26/2013) nên mất vài giờ — <b>không kịp cho ca cần
                      trong 2 giờ</b>. Vẫn nên mở, nhưng phải tìm song song đường khác.
                    </p>
                  )}

                  {(matchResults.sos_depleted_facilities?.length ?? 0) > 0 && (
                    <p className="sos-advice-why">
                      Cơ sở sẽ tụt sát ngưỡng:{' '}
                      <b>{(matchResults.sos_depleted_facilities ?? [])
                        .map(id => facilities?.find(f => f.id === id)?.name ?? id)
                        .join(', ')}</b>
                    </p>
                  )}

                  {/* "Bất kỳ (tương hợp)" hợp lý khi TÌM KHO — máy chủ tự suy ra nhóm
                      nào truyền được. Nhưng gọi người hiến thì phải biết cần nhóm
                      nào: không có ABO thì lời kêu gọi đi cho "mọi nhóm", làm phiền
                      cả người không dùng được và số đếm cũng vô nghĩa. */}
                  {sosOpened ? (
                    <p className="sos-advice-done">✓ {sosOpened}</p>
                  ) : !formData.abo ? (
                    <p className="sos-advice-warn" style={{ marginBottom: 0 }}>
                      Chọn <b>nhóm máu ABO cụ thể</b> ở trên rồi tìm lại thì mới mở được
                      lời kêu gọi. Tìm kho thì để “bất kỳ” được, nhưng gọi người hiến mà
                      không biết cần nhóm nào là làm phiền nhầm người.
                    </p>
                  ) : (
                    <button
                      className="btn btn-primary"
                      disabled={openSos.isPending}
                      onClick={() => openSos.mutate()}
                    >
                      {openSos.isPending
                        ? 'Đang mở…'
                        : `Mở lời kêu gọi · ${matchResults.sos_target_count} người · ` +
                          `vòng ${matchResults.sos_start_ring} · ` +
                          `${matchResults.sos_urgency === 'routine' ? 'luân chuyển' : 'khẩn'}`}
                    </button>
                  )}
                </div>
              )}

              <div className="card" style={{ padding: 0 }}>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Nhóm máu</th>
                        <th>Điểm</th>
                        <th>Giải thích</th>
                        <th>Còn lại</th>
                        <th>Cơ sở nguồn</th>
                        <th>Thao tác</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matchResults.results.filter(r => r.compatible).map((r, i) => (
                        <tr key={r.unit_id}>
                          <td style={{ fontWeight: 700, color: i === 0 ? 'var(--bb-red)' : 'var(--bb-gray-500)' }}>
                            {i === 0 ? '★' : r.rank}
                          </td>
                          <td style={{ fontWeight: 600 }}>
                            {/* Blood type would come from unit data — showing score-based info */}
                            <span className={`badge badge-${r.score > 0.8 ? 'normal' : r.score > 0.5 ? 'warning' : 'routine'}`}>
                              {r.reason_text.split(',')[0]}
                            </span>
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div className="score-bar" style={{ width: 60 }}>
                                <div className="score-bar-fill" style={{
                                  width: `${r.score * 100}%`,
                                  background: r.score > 0.8 ? 'var(--bb-green)' :
                                               r.score > 0.5 ? 'var(--bb-amber)' : 'var(--bb-red)',
                                }} />
                              </div>
                              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                                {(r.score * 100).toFixed(0)}%
                              </span>
                            </div>
                          </td>
                          <td style={{ fontSize: 12, maxWidth: 280 }}>{r.reason_text}</td>
                          <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                            {r.eta_seconds ? `${Math.round(r.eta_seconds / 60)} phút` : '—'}
                          </td>
                          <td style={{ fontSize: 12 }}>{r.unit_id.slice(0, 8)}...</td>
                          <td>
                            {i === 0 && (
                              <button className="btn btn-primary" style={{ fontSize: 12, padding: '4px 12px' }}
                                onClick={() => approveRequest.mutate({ reqId: matchResults.request_id, approvedBy: 'console-user' })}>
                                Đề xuất
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Blocked units */}
              {matchResults.results.filter(r => !r.compatible).length > 0 && (
                <div className="card" style={{ borderLeft: '3px solid var(--bb-gray-400)' }}>
                  <h4 style={{ marginBottom: 8, color: 'var(--bb-gray-600)' }}>Đơn vị bị loại</h4>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Lý do loại</th></tr></thead>
                      <tbody>
                        {matchResults.results.filter(r => !r.compatible).slice(0, 5).map(r => (
                          <tr key={r.unit_id}>
                            <td style={{ fontSize: 12, color: 'var(--bb-gray-600)' }}>{r.reason_text}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 8 }}>
                <strong>Lưu ý:</strong> Nút bấm phải là "Đề xuất", không phải "Điều chuyển" — thẩm quyền phê duyệt thuộc điều phối viên và bác sĩ.
              </div>

              <button className="btn btn-secondary" style={{ marginTop: 16 }}
                onClick={() => { setStep('request'); setRequestId(null) }}>
                ← Tạo yêu cầu mới
              </button>
            </>
          )}
        </>
      )}
    </>
  )
}