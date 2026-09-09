import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api, type Facility, type FacilityStock, type SosEvent, type DensityCell } from '../lib/api'
import { COMPONENT_LABELS } from '../lib/constants'

/**
 * Bản đồ điều phối — ba lớp trên cùng một khung nhìn.
 *
 *   1. Bệnh viện  — chấm to nhỏ theo tồn kho của nhóm máu đang lọc
 *   2. Nhu cầu    — ca SOS đang mở, đỏ và nhấp nháy nếu cấp cứu
 *   3. Người hiến — ô lưới H3 tô đậm theo mật độ
 *
 * Lớp 3 KHÔNG BAO GIỜ là chấm cá nhân. Hệ thống chỉ lưu ô lưới ~1,2 km chứ
 * không lưu toạ độ, và máy chủ còn ẩn hẳn ô nào có dưới `min_donors` người
 * (k-ẩn danh). Chấm từng người lên bản đồ sẽ phá đúng cam kết riêng tư mà cả
 * hệ thống dựa vào — nên đây là giới hạn cố ý, không phải thiếu sót.
 */

const ABO_OPTIONS = ['O', 'A', 'B', 'AB']
const HCMC_CENTER: [number, number] = [10.776, 106.68]

/** Màu theo mức tồn: đỏ = cạn, xanh = dồi dào. */
function stockColor(count: number): string {
  if (count === 0) return '#991b1b'
  if (count < 20) return '#dc2626'
  if (count < 60) return '#f59e0b'
  if (count < 150) return '#65a30d'
  return '#15803d'
}

function stockLabel(count: number): string {
  if (count === 0) return 'Hết'
  if (count < 20) return 'Rất thấp'
  if (count < 60) return 'Thấp'
  if (count < 150) return 'Đủ'
  return 'Dồi dào'
}

export default function MapView() {
  const [abo, setAbo] = useState('O')
  const [rh, setRh] = useState('+')
  const [component, setComponent] = useState('RBC')

  // Chủ đề đang hiển thị thật sự (đã giải quyết xong "theo hệ thống").
  const [dark, setDark] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const resolve = () => {
      const choice = document.documentElement.getAttribute('data-theme')
      setDark(choice === 'dark' || (choice !== 'light' && mq.matches))
    }
    resolve()
    mq.addEventListener('change', resolve)
    // Nút chuyển chủ đề đổi thuộc tính trên <html>, theo dõi để nền đổi theo.
    const obs = new MutationObserver(resolve)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', resolve); obs.disconnect() }
  }, [])

  const boxRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  const { data: facilities } = useQuery({
    queryKey: ['facilities'],
    queryFn: () => api.listFacilities(),
  })

  const { data: stock } = useQuery({
    queryKey: ['stock-by-facility', component],
    queryFn: () => api.inventoryByFacility(component),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  })

  const { data: events } = useQuery({
    queryKey: ['open-sos'],
    queryFn: () => api.listOpenSosEvents(),
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
  })

  const { data: density } = useQuery({
    queryKey: ['donor-density', abo, rh],
    // Để nguyên ngưỡng k-ẩn danh mặc định của máy chủ (3). Hạ xuống 1 thì bản
    // đồ trông "đầy" hơn nhưng một ô chỉ có đúng một người là đủ để lần ra
    // người đó — chính thứ cả hệ thống cam kết không làm.
    queryFn: () => api.donorDensity({ abo, rh }),
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })

  const bloodType = `${abo}${rh}`

  /** Tồn kho của nhóm máu đang chọn, gom theo cơ sở. */
  const stockByFacility = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of (stock ?? []) as FacilityStock[]) {
      if (r.blood_type !== bloodType) continue
      m.set(r.facility_id, (m.get(r.facility_id) ?? 0) + r.count)
    }
    return m
  }, [stock, bloodType])

  // ── Dựng bản đồ một lần ────────────────────────────────────────
  useEffect(() => {
    if (mapRef.current || !boxRef.current) return
    const map = L.map(boxRef.current, { zoomControl: true }).setView(HCMC_CENTER, 12)
    mapRef.current = map
    layerRef.current = L.layerGroup().addTo(map)

    // Leaflet đo khung ngay lúc dựng; nếu thẻ cha còn đang bố trí thì bản đồ
    // ra kích thước 0 và chỉ hiện một mảng xám.
    setTimeout(() => map.invalidateSize(), 0)

    return () => { map.remove(); mapRef.current = null }
  }, [])

  // ── Nền bản đồ ─────────────────────────────────────────────────
  //
  // Hai nguồn đã thử và LOẠI, ghi lại để đừng ai quay lại:
  //   · tile.openstreetmap.org — chính sách OSM chặn ứng dụng không định danh,
  //     trình duyệt nhận 503 hàng loạt và bản đồ ra một mảng xám.
  //   · basemaps.cartocdn.com — nay đòi API key, in đè chữ "API KEY REQUIRED"
  //     lên khắp nền.
  // Máy chủ của cộng đồng OSM Đức phục vụ được, không cần khoá, cùng dữ liệu OSM.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const tiles = L.tileLayer('https://tile.openstreetmap.de/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(map)
    return () => { tiles.remove() }
  }, [])

  // ── Vẽ lại ba lớp mỗi khi dữ liệu đổi ──────────────────────────
  useEffect(() => {
    const layer = layerRef.current
    if (!layer || !facilities) return
    layer.clearLayers()

    // Lớp 3 vẽ TRƯỚC để nằm dưới cùng — nếu không, ô lưới sẽ che mất chấm
    // bệnh viện, đúng chỗ người dùng cần bấm.
    for (const cell of (density?.cells ?? []) as DensityCell[]) {
      L.polygon(cell.boundary, {
        color: '#7c3aed',
        weight: 1,
        fillColor: '#7c3aed',
        // Đậm dần theo số người, chặn trần để ô đông không thành khối đặc.
        fillOpacity: Math.min(0.1 + cell.count * 0.04, 0.45),
      })
        .bindPopup(
          `<b>${cell.count} người hiến ${bloodType}</b><br>` +
          `Ô lưới H3 <code>${cell.h3_cell}</code><br>` +
          `<small>Đây là một VÙNG ~1,2 km, không phải vị trí của ai.</small>`,
        )
        .addTo(layer)
    }

    // Lớp 1 — bệnh viện
    const facById = new Map((facilities as Facility[]).map(f => [f.id, f]))
    for (const f of facilities as Facility[]) {
      const count = stockByFacility.get(f.id) ?? 0
      L.circleMarker([f.lat, f.lon], {
        radius: 9 + Math.min(Math.sqrt(count), 13),
        color: '#fff',
        weight: 2,
        fillColor: stockColor(count),
        fillOpacity: 0.92,
      })
        .bindPopup(
          `<b>${f.name}</b><br>` +
          `${bloodType} · ${COMPONENT_LABELS[component] ?? component}: ` +
          `<b>${count}</b> đơn vị — ${stockLabel(count)}<br>` +
          `<small>Chỉ đếm đơn vị còn hạn.</small>`,
        )
        .addTo(layer)
    }

    // Lớp 2 — ca đang cần, vẽ SAU CÙNG để luôn nằm trên
    //
    // GOM theo cơ sở, một ghim cho mỗi bệnh viện. Một bệnh viện có thể đang mở
    // nhiều ca cùng lúc; ghim từng ca đúng vào toạ độ cơ sở thì chúng chồng
    // khít và người điều phối tưởng nơi đó chỉ có một ca. Rải ra quanh cơ sở
    // cũng không ổn — làm vậy là đặt ca vào chỗ nó không nằm ở đó.
    const byFacility = new Map<string, SosEvent[]>()
    for (const ev of (events ?? []) as SosEvent[]) {
      if (!ev.facility_id) continue
      const list = byFacility.get(ev.facility_id) ?? []
      list.push(ev)
      byFacility.set(ev.facility_id, list)
    }

    for (const [facilityId, list] of byFacility) {
      const f = facById.get(facilityId)
      if (!f) continue

      const emergency = list.some(e => e.urgency === 'emergency')
      // Nhãn trên ghim: một ca thì hiện nhóm máu, nhiều ca thì hiện số lượng.
      const label = list.length === 1
        ? `${list[0].abo ?? ''}${list[0].rh ?? ''}`
        : `${list.length} ca`

      const lines = list
        .map(e => {
          const urgent = e.urgency === 'emergency' ? ' · <b style="color:#dc2626">CẤP CỨU</b>' : ''
          const comp = COMPONENT_LABELS[e.component_code ?? ''] ?? e.component_code ?? ''
          return `<li><b>${e.abo ?? ''}${e.rh ?? ''}</b> — ${comp}<br>` +
                 `<small>vòng ${e.ring} · nhận lời ${e.accept_count}/${e.target_count}${urgent}</small></li>`
        })
        .join('')

      L.marker([f.lat, f.lon], {
        icon: L.divIcon({
          className: 'sos-pin',
          html:
            `<div class="sos-pin-dot${emergency ? ' sos-pin-emergency' : ''}">${label}</div>`,
          iconSize: [34, 34],
          iconAnchor: [17, 17],
        }),
      })
        .bindPopup(
          `<b>${f.name}</b><br>` +
          `<span style="color:#dc2626;font-weight:600">Đang cần máu — ${list.length} ca</span>` +
          `<ul style="margin:6px 0 0;padding-left:17px">${lines}</ul>`,
        )
        .addTo(layer)
    }
  }, [facilities, stockByFacility, events, density, bloodType, component])

  const totalStock = useMemo(
    () => [...stockByFacility.values()].reduce((a, b) => a + b, 0),
    [stockByFacility],
  )
  const donorTotal = (density?.cells ?? []).reduce((a, c) => a + c.count, 0)

  return (
    <>
      <h2>Bản đồ điều phối</h2>
      <p className="subtitle">
        Tồn kho theo nhóm máu · ca đang cần · mật độ người hiến — trên cùng một khung nhìn
      </p>

      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Nhóm máu ABO</label>
            <select value={abo} onChange={e => setAbo(e.target.value)}>
              {ABO_OPTIONS.map(a => <option key={a} value={a}>Nhóm {a}</option>)}
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
            <label>Chế phẩm</label>
            <select value={component} onChange={e => setComponent(e.target.value)}>
              <option value="RBC">Khối hồng cầu</option>
              <option value="PLT">Khối tiểu cầu</option>
              <option value="FFP">Huyết tương tươi đông lạnh</option>
            </select>
          </div>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-number">{totalStock}</div>
          <div className="stat-label">Đơn vị {bloodType} còn hạn</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{events?.length ?? 0}</div>
          <div className="stat-label">Ca đang cần máu</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{donorTotal}</div>
          <div className="stat-label">Người hiến {bloodType} trong vùng</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{density?.cells.length ?? 0}</div>
          <div className="stat-label">Ô lưới có người hiến</div>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div ref={boxRef} className={dark ? 'bb-map bb-map-dark' : 'bb-map'}
             style={{ height: 560, width: '100%' }} />
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Đọc bản đồ</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, fontSize: 13.5 }}>
          <Legend color="#15803d" text="Kho dồi dào (≥150)" />
          <Legend color="#65a30d" text="Đủ (60–149)" />
          <Legend color="#f59e0b" text="Thấp (20–59)" />
          <Legend color="#dc2626" text="Rất thấp (<20)" />
          <Legend color="#991b1b" text="Hết" />
          <Legend color="#7c3aed" text="Ô lưới có người hiến" />
        </div>
        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 14, marginBottom: 0 }}>
          Chấm to nhỏ theo số đơn vị. Ghim vuông là ca đang cần máu — viền đỏ nhấp nháy nghĩa là cấp cứu.
          Vùng tím là <b>ô lưới H3 ~1,2 km</b>, KHÔNG phải vị trí của người hiến nào: hệ thống chỉ lưu ô
          lưới chứ không lưu toạ độ, nên bản đồ này không thể chỉ ra ai đang ở đâu — kể cả khi muốn.
          {density && density.suppressed_cells > 0 && (
            <> Có <b>{density.suppressed_cells}</b> ô bị ẩn vì dưới ngưỡng {density.min_donors} người.</>
          )}
        </p>
      </div>
    </>
  )
}

function Legend({ color, text }: { color: string; text: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
      <span style={{ width: 14, height: 14, borderRadius: 4, background: color, flexShrink: 0 }} />
      {text}
    </span>
  )
}
