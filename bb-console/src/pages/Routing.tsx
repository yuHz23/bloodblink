import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * Routing page — ETA comparison between straight-line and road routing.
 * Demonstrates that BLOODBLINK uses real travel times, not just distance.
 */

const FACILITIES: Record<string, { name: string; lat: number; lon: number }> = {
  'fac-bv-tmhh': { name: 'BV Truyền máu Huyết học', lat: 10.7869, lon: 106.6854 },
  'fac-bv-cho-ray': { name: 'BV Chợ Rẫy', lat: 10.7635, lon: 106.6690 },
  'fac-bv-ung-buou': { name: 'BV Ung Bướu', lat: 10.7736, lon: 106.6973 },
  'fac-bv-nhi-dong': { name: 'BV Nhi Đồng 1', lat: 10.7905, lon: 106.6940 },
  'fac-bv-pham-ngoc-thach': { name: 'BV Phạm Ngọc Thạch', lat: 10.7811, lon: 106.6728 },
}

export default function Routing() {
  const [selectedFacility, setSelectedFacility] = useState('fac-bv-tmhh')

  // Cả hai truy vấn chạy cả khi cửa sổ bị che — xem ghi chú ở Dashboard.tsx.
  // ETA phụ thuộc tình hình giao thông nên đây chính là thứ không được để cũ.
  const { data: pairData, isLoading: pairsLoading } = useQuery({
    queryKey: ['hcmc-pairs'],
    queryFn: () => api.compareHcmcPairs(),
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })

  const { data: facilityEta, isLoading: etaLoading } = useQuery({
    queryKey: ['facility-eta', selectedFacility],
    queryFn: () => api.getEtaFromFacility(selectedFacility),
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })


  const providerLabel = (provider: string) => {
    switch (provider) {
      case 'osrm': return 'OSRM (đường thật)'
      case 'straight_line': return 'Đường chim bay'
      case 'osrm_fallback': return 'OSRM → chim bay (dự phòng)'
      default: return provider
    }
  }

  return (
    <>
      <h2>Định tuyến & ETA</h2>
      <p className="subtitle">So sánh thời gian đến nơi: đường chim bay vs đường bộ thật — chứng minh ETA đáng tin cậy</p>

      {/* Architecture note */}
      <div className="card" style={{ borderLeft: '3px solid var(--bb-blue)' }}>
        <h4 style={{ marginBottom: 8 }}>Kiến trúc RoutingProvider</h4>
        <div style={{ fontSize: 13, color: 'var(--bb-gray-600)', lineHeight: 1.7 }}>
          <p>• <strong>RoutingProvider interface</strong> — trừu tượng hóa, cho phép đổi OSRM sang Google Maps / Grab API sau này</p>
          <p>• <strong>StraightLineRouting</strong> (haversine) — luôn khả dụng, tốc độ xe: ô tô 25 km/h, xe máy 30 km/h, cấp cứu 40 km/h</p>
          <p>• <strong>OSRMRouting</strong> — self-hosted trên OSM Vietnam extract, chạy offline, không giới hạn truy vấn</p>
          <p>• <strong>⚠️ Không có dữ liệu giao thông thời gian thực</strong> — phải ghi rõ trong demo</p>
          <p>• ETA được dùng trong matching engine (yếu tố <code>time_margin</code>) để xếp hạng nguồn gần nhất</p>
        </div>
      </div>

      {/* Provider switch */}
      <div className="card" style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ margin: 0, minWidth: 200 }}>
          <label>Provider định tuyến</label>
          <select onChange={e => api.setRoutingProvider(e.target.value).then(() => window.location.reload())}>
            <option value="straight_line">Đường chim bay (mặc định)</option>
            <option value="osrm">OSRM (localhost:5000)</option>
          </select>
        </div>
        <div style={{ fontSize: 12, color: 'var(--bb-gray-500)' }}>
          Provider hiện tại: <strong>{pairData?.pairs?.[0]?.road?.provider === 'osrm' ? 'OSRM' : 'Đường chim bay'}</strong>
        </div>
      </div>

      {/* HCMC pair comparisons */}
      <div className="card">
        <h3 style={{ marginBottom: 16 }}>So sánh ETA 20 cặp cơ sở y tế TP.HCM</h3>

        {pairsLoading ? (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--bb-gray-500)' }}>
            Đang tải so sánh ETA...
          </div>
        ) : pairData && (
          <>
            {/* Summary stats */}
            <div className="stat-grid" style={{ marginBottom: 16 }}>
              <div className="stat-card">
                <div className="stat-number">{pairData.summary.total_pairs}</div>
                <div className="stat-label">Cặp cơ sở</div>
              </div>
              <div className="stat-card">
                <div className="stat-number" style={{ color: 'var(--bb-blue)' }}>
                  {pairData.summary.avg_straight_line_min.toFixed(1)}'
                </div>
                <div className="stat-label">TB chim bay</div>
              </div>
              <div className="stat-card">
                <div className="stat-number" style={{ color: 'var(--bb-amber)' }}>
                  {pairData.summary.avg_road_min.toFixed(1)}'
                </div>
                <div className="stat-label">TB đường bộ</div>
              </div>
              <div className="stat-card">
                <div className="stat-number" style={{ color: 'var(--bb-red)' }}>
                  +{pairData.summary.avg_extra_time_pct.toFixed(0)}%
                </div>
                <div className="stat-label">Chênh lệch TB</div>
              </div>
            </div>

            {/* Pair table */}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Từ</th>
                    <th>Đến</th>
                    <th>Chim bay</th>
                    <th>Đường bộ</th>
                    <th>Chênh</th>
                    <th>%</th>
                  </tr>
                </thead>
                <tbody>
                  {pairData.pairs.slice(0, 10).map((pair, i) => (
                    <tr key={i}>
                      <td style={{ fontSize: 12 }}>{pair.from.name.replace('Bệnh viện ', 'BV ')}</td>
                      <td style={{ fontSize: 12 }}>{pair.to.name.replace('Bệnh viện ', 'BV ')}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {pair.straight_line.duration_min.toFixed(1)}'
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
                        {pair.road.duration_min.toFixed(1)}'
                      </td>
                      <td style={{
                        fontFamily: 'var(--font-mono)', fontSize: 12,
                        color: Math.abs(pair.difference.extra_minutes) > 2 ? 'var(--bb-red)' : 'var(--bb-green)',
                      }}>
                        {pair.difference.extra_minutes > 0 ? '+' : ''}{pair.difference.extra_minutes.toFixed(1)}'
                      </td>
                      <td style={{
                        fontFamily: 'var(--font-mono)', fontSize: 12,
                        color: Math.abs(pair.difference.percentage) > 10 ? 'var(--bb-amber)' : 'var(--bb-green)',
                      }}>
                        {pair.difference.percentage > 0 ? '+' : ''}{pair.difference.percentage.toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ fontSize: 12, color: 'var(--bb-gray-500)', marginTop: 8 }}>
              {pairData.summary.note}
            </div>
          </>
        )}
      </div>

      {/* ETA from one facility to all others */}
      <div className="card">
        <h3 style={{ marginBottom: 16 }}>ETA từ một cơ sở đến tất cả các cơ sở khác</h3>

        <div className="form-group" style={{ maxWidth: 300 }}>
          <label>Chọn cơ sở xuất phát</label>
          <select value={selectedFacility} onChange={e => setSelectedFacility(e.target.value)}>
            {Object.entries(FACILITIES).map(([id, fac]) => (
              <option key={id} value={id}>{fac.name}</option>
            ))}
          </select>
        </div>

        {etaLoading ? (
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--bb-gray-500)' }}>
            Đang tính ETA...
          </div>
        ) : facilityEta && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Đến</th>
                  <th>Khoảng cách</th>
                  <th>Thời gian</th>
                  <th>Provider</th>
                </tr>
              </thead>
              <tbody>
                {facilityEta.to_facilities.map((f, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 600 }}>{f.to_name.replace('Bệnh viện ', 'BV ')}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {f.distance_m >= 1000
                        ? `${(f.distance_m / 1000).toFixed(1)} km`
                        : `${Math.round(f.distance_m)} m`}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
                      {f.duration_min.toFixed(1)} phút
                    </td>
                    <td>
                      <span className={`badge badge-${f.provider === 'osrm' ? 'normal' : 'warning'}`}>
                        {providerLabel(f.provider)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* TT 26/2013 compliance note */}
      <div className="card" style={{ fontSize: 13, color: 'var(--bb-gray-600)', lineHeight: 1.7 }}>
        <h4 style={{ marginBottom: 8 }}>Tuân thủ Điều 20 TT 26/2013/TT-BYT</h4>
        <p>• <strong>Hai chế độ ngưỡng nhiệt:</strong> bảo quản (storage) và vận chuyển (transport) khác nhau — BB-Box phân biệt được</p>
        <p>• ETA từ routing engine giúp tính toán <code>time_margin</code> trong matching — yếu tố xếp hạng nguồn máu gần nhất</p>
        <p>• <strong>Emergency mode</strong> (40 km/h) dùng cho cấp cứu SOS, <strong>car mode</strong> (25 km/h) dùng cho luân chuyển thường</p>
        <p style={{ color: 'var(--bb-red)', fontWeight: 600 }}>
          ⚠️ ETA không bao gồm dữ liệu giao thông thời gian thực — chỉ là ước tính dựa trên khoảng cách đường.
        </p>
      </div>
    </>
  )
}