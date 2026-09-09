import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck, ShieldAlert, RefreshCw, Lock } from 'lucide-react'
import { api, type AuditEntry } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * Nhật ký ghi vết — mặt tiền của phần kiểm toán làm ở P4.
 *
 * Trước đây thanh bên có mục "Nhật ký" trỏ tới `/reports` nhưng không có route
 * nào khớp: bấm vào là mục sáng lên và khung nội dung trống. Toàn bộ nhóm
 * endpoint `/api/audit` không có màn hình nào đọc nó.
 *
 * Nhật ký cho biết cơ sở nào tra ai lúc nào nên TỰ NÓ là dữ liệu nhạy cảm —
 * backend chỉ cho vai trò `admin`, màn này phản chiếu đúng ràng buộc đó.
 */

/** Nhãn tiếng Việt cho từng hành động, kèm mức độ để tô màu. */
const ACTIONS: Record<string, { label: string; tone: 'normal' | 'warning' | 'urgent' }> = {
  'auth.login':          { label: 'Đăng nhập',              tone: 'normal' },
  'auth.login_failed':   { label: 'Đăng nhập hỏng',         tone: 'warning' },
  'donor.register':      { label: 'Đăng ký người hiến',     tone: 'normal' },
  'donor.verify':        { label: 'Xác minh người hiến',    tone: 'normal' },
  'donor.search':        { label: 'Tra người hiến quanh ô', tone: 'warning' },
  'donor.list':          { label: 'Xem danh sách người hiến', tone: 'warning' },
  'sos.open':            { label: 'Mở lời kêu gọi',         tone: 'urgent' },
  'sos.escalate':        { label: 'Nâng vòng',              tone: 'urgent' },
  'sos.respond':         { label: 'Người hiến trả lời',     tone: 'normal' },
  'sos.contact_reveal':  { label: 'Xem liên hệ người nhận lời', tone: 'urgent' },
}

function describe(action: string) {
  return ACTIONS[action] ?? { label: action, tone: 'normal' as const }
}

function formatAt(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('vi-VN', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

/** Rút gọn băm để đọc được trong bảng mà vẫn đối chiếu được bằng mắt. */
function shortHash(h: string | null) {
  return h ? `${h.slice(0, 8)}…${h.slice(-4)}` : '—'
}

export default function Reports() {
  const { session } = useAuth()
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')

  const isAdmin = session?.role === 'admin'

  const verify = useQuery({
    queryKey: ['audit-verify'],
    queryFn: () => api.verifyAudit(),
    enabled: isAdmin,
    refetchOnWindowFocus: false,
  })

  const entries = useQuery({
    queryKey: ['audit', action, actor],
    queryFn: () => api.listAudit({ action: action || undefined, actor: actor || undefined, limit: 200 }),
    enabled: isAdmin,
  })

  const rows: AuditEntry[] = entries.data ?? []

  // Thống kê theo hành động, để nhìn ra ngay cái gì đang xảy ra nhiều nhất.
  const byAction = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of rows) counts.set(r.action, (counts.get(r.action) ?? 0) + 1)
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [rows])

  if (!isAdmin) {
    return (
      <>
        <h2>Nhật ký ghi vết</h2>
        <p className="subtitle">Chuỗi băm append-only · ai tra ai, lúc nào</p>
        <div className="card" style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <Lock size={18} style={{ marginTop: 2, flexShrink: 0, color: 'var(--text-muted)' }} />
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Chỉ quản trị hệ thống đọc được</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              Nhật ký cho biết cơ sở nào tra người hiến nào vào lúc nào, nên bản thân nó
              cũng là dữ liệu nhạy cảm. Tài khoản đang dùng có vai trò{' '}
              <code>{session?.role ?? 'không rõ'}</code>.
            </div>
          </div>
        </div>
      </>
    )
  }

  const v = verify.data

  return (
    <>
      <h2>Nhật ký ghi vết</h2>
      <p className="subtitle">
        Chuỗi băm append-only · mỗi dòng băm cả dòng trước nó, sửa giữa chừng là phát hiện được
      </p>

      {/* Tình trạng toàn vẹn chuỗi */}
      <div className="card" style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
        {v?.ok
          ? <ShieldCheck size={22} style={{ color: 'var(--bb-green, #15803d)', flexShrink: 0, marginTop: 1 }} />
          : <ShieldAlert size={22} style={{ color: 'var(--bb-red, #c62828)', flexShrink: 0, marginTop: 1 }} />}

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 650, marginBottom: 3 }}>
            {verify.isLoading ? 'Đang kiểm chuỗi…'
              : v?.ok ? 'Chuỗi liền mạch — chưa phát hiện dòng nào bị sửa hoặc xoá'
              : 'CHUỖI ĐÃ GÃY'}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {v
              ? <>Đã kiểm {v.checked}/{v.total} dòng · đầu chuỗi <code>{shortHash(v.head_hash)}</code>
                  {v.broken_at && <> · hỏng từ dòng <code>{v.broken_at}</code></>}</>
              : verify.error ? 'Không đọc được kết quả kiểm tra.' : '…'}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 7 }}>
            Kết quả này không chứng minh “chưa ai sửa”; nó chứng minh “nếu có sửa thì phát hiện được”.
          </div>
        </div>

        <button className="btn btn-secondary" onClick={() => { verify.refetch(); entries.refetch() }}>
          <RefreshCw size={14} /> Kiểm lại
        </button>
      </div>

      {/* Đếm theo hành động */}
      {byAction.length > 0 && (
        <div className="stat-grid">
          {byAction.slice(0, 4).map(([act, n]) => (
            <div className="stat-card" key={act}>
              <div className="stat-number">{n}</div>
              <div className="stat-label">{describe(act).label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Bộ lọc */}
      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Hành động</label>
            <select value={action} onChange={e => setAction(e.target.value)}>
              <option value="">Tất cả</option>
              {Object.entries(ACTIONS).map(([key, { label }]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Mã chủ thể</label>
            <input
              value={actor}
              onChange={e => setActor(e.target.value)}
              placeholder="user-choray hoặc mã người hiến"
            />
          </div>
        </div>
      </div>

      {/* Bảng nhật ký */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>
          {entries.isFetching ? 'Đang tải…' : `${rows.length} dòng gần nhất`}
        </h3>

        {rows.length === 0 && !entries.isFetching ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0 }}>
            Không có dòng nào khớp bộ lọc.
          </p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Thời điểm</th>
                  <th>Hành động</th>
                  <th>Chủ thể</th>
                  <th>Chi tiết</th>
                  <th>Băm</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const { label, tone } = describe(r.action)
                  return (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                        {formatAt(r.at)}
                      </td>
                      <td><span className={`badge badge-${tone}`}>{label}</span></td>
                      <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>{r.actor}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 340 }}>
                        {Object.keys(r.payload ?? {}).length === 0
                          ? '—'
                          : Object.entries(r.payload)
                              .map(([k, val]) => `${k}=${val === null ? '∅' : String(val)}`)
                              .join(' · ')}
                      </td>
                      <td
                        style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11,
                                 color: 'var(--text-muted)', whiteSpace: 'nowrap' }}
                        title={`hash ${r.hash}\nprev ${r.prev_hash ?? '(đầu chuỗi)'}`}
                      >
                        {shortHash(r.hash)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
