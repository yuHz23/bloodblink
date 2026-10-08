import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

const FACILITIES: Record<string, { name: string }> = {
  'fac-bv-tmhh': { name: 'BV Truyền máu Huyết học' },
  'fac-bv-cho-ray': { name: 'BV Chợ Rẫy' },
  'fac-bv-ung-buou': { name: 'BV Ung Bướu' },
  'fac-bv-nhi-dong': { name: 'BV Nhi Đồng 1' },
  'fac-bv-pham-ngoc-thach': { name: 'BV Phạm Ngọc Thạch' },
}

export default function Routing() {
  const [selectedFacility, setSelectedFacility] = useState('fac-bv-tmhh')
  const { data: facilityEta, isLoading, error } = useQuery({
    queryKey: ['facility-eta', selectedFacility],
    queryFn: () => api.getEtaFromFacility(selectedFacility),
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })

  return (
    <>
      <h2>Định tuyến đường bộ</h2>
      <p className="subtitle">ETA và khoảng cách theo mạng đường OSRM; tuyến đường hiển thị trong trang Bản đồ.</p>

      <div className="card" style={{ borderLeft: '3px solid var(--bb-blue)' }}>
        <strong>Chỉ dùng tuyến đường bộ</strong>
        <p style={{ marginBottom: 0, fontSize: 13, color: 'var(--bb-gray-600)', lineHeight: 1.7 }}>
          BB-Core lấy hình học tuyến từ OSRM để vẽ trên bản đồ. Nếu OSRM không khả dụng,
          hệ thống báo chưa có tuyến thay vì nối hai cơ sở bằng đường thẳng. ETA không gồm dữ liệu giao thông thời gian thực.
        </p>
      </div>

      <div className="card">
        <h3 style={{ marginBottom: 16 }}>ETA từ một cơ sở đến các cơ sở khác</h3>
        <div className="form-group" style={{ maxWidth: 300 }}>
          <label htmlFor="routing-facility">Chọn cơ sở xuất phát</label>
          <select id="routing-facility" value={selectedFacility} onChange={e => setSelectedFacility(e.target.value)}>
            {Object.entries(FACILITIES).map(([id, facility]) => (
              <option key={id} value={id}>{facility.name}</option>
            ))}
          </select>
        </div>

        {isLoading && <div role="status" style={{ padding: 24, color: 'var(--bb-gray-500)' }}>Đang tính ETA đường bộ…</div>}
        {error && <div role="alert" style={{ color: 'var(--bb-red)' }}>Không lấy được tuyến OSRM. Hãy kiểm tra dịch vụ định tuyến.</div>}
        {facilityEta && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Đến</th><th>Khoảng cách đường bộ</th><th>ETA</th></tr>
              </thead>
              <tbody>
                {facilityEta.to_facilities.map(facility => (
                  <tr key={facility.to_facility_id}>
                    <td style={{ fontWeight: 600 }}>{facility.to_name.replace('Bệnh viện ', 'BV ')}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      {facility.distance_m >= 1000
                        ? `${(facility.distance_m / 1000).toFixed(1)} km`
                        : `${Math.round(facility.distance_m)} m`}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600 }}>
                      {facility.duration_min.toFixed(1)} phút
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
