/**
 * BB-Console — Constants and display helpers for blood components.
 * Maps directly to TT 26/2013/TT-BYT regulations.
 */

// Component display names (Vietnamese)
export const COMPONENT_LABELS: Record<string, string> = {
  RBC: 'Khối hồng cầu',
  PLT: 'Khối tiểu cầu',
  FFP: 'Huyết tương tươi đông lạnh',
  CRYO: 'Kết tủa lạnh',
  WB: 'Máu toàn phần',
};

// Short labels for dashboard
export const COMPONENT_SHORT: Record<string, string> = {
  RBC: 'Hồng cầu',
  PLT: 'Tiểu cầu',
  FFP: 'Huyết tương',
  CRYO: 'Kết tủa',
  WB: 'Toàn phần',
};

// Urgency labels
export const URGENCY_LABELS: Record<string, { label: string; color: string; desc: string }> = {
  routine: {
    label: 'Luân chuyển',
    color: '#3b82f6',   // blue
    desc: 'Điều chuyển chủ động — tối ưu tồn kho',
  },
  urgent: {
    label: 'Cấp bách',
    color: '#f59e0b',   // amber
    desc: 'Cần trong 6 giờ',
  },
  emergency: {
    label: 'Cấp cứu',
    color: '#ef4444',   // red
    desc: 'Cần trong 2 giờ — tính mạng bệnh nhân',
  },
};

// Shelf life per TT 26/2013/TT-BYT
export const SHELF_LIFE: Record<string, { days: number | null; note: string }> = {
  RBC: { days: 42, note: 'Hệ kín, 2–6°C (Điều 24.3)' },
  PLT: { days: 5, note: '20–24°C lắc liên tục (Điều 30)' },
  FFP: { days: null, note: '12 tháng (−18…−25°C) / 24 tháng (≤−25°C) (Điều 33)' },
  CRYO: { days: null, note: '12 tháng (−18…−25°C) (Điều 33)' },
  WB: { days: 42, note: 'Hệ kín, 2–6°C' },
};

// Temperature thresholds — TWO modes (Art 20 TT 26/2013/TT-BYT)
export const TEMP_THRESHOLDS: Record<string, { storage: [number, number]; transport: [number, number] }> = {
  WB:  { storage: [2, 6],   transport: [1, 10] },
  RBC: { storage: [2, 6],   transport: [1, 10] },
  PLT: { storage: [20, 24], transport: [20, 24] },
  FFP: { storage: [-25, -18], transport: [-25, -18] },
};

// Blood type display
export function bloodTypeLabel(abo: string, rh: string): string {
  return `${abo}${rh === '+' ? '⁺' : '⁻'}`;
}

// Urgency badge color
export function urgencyBadge(urgency: string): { bg: string; text: string } {
  const u = URGENCY_LABELS[urgency];
  if (!u) return { bg: '#e5e7eb', text: '#374151' };
  return { bg: `${u.color}20`, text: u.color };
}

// Format hours remaining
export function formatHoursRemaining(hours: number): string {
  if (hours < 0) return 'Đã hết hạn';
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = Math.floor(hours / 24);
  const h = Math.round(hours % 24);
  return h > 0 ? `${days} ngày ${h}h` : `${days} ngày`;
}

// Urgency classification for FEFO view
export function classifyUrgency(component: string, hoursRemaining: number): 'expired' | 'critical' | 'warning' | 'normal' {
  if (hoursRemaining <= 0) return 'expired';
  if (component === 'PLT' && hoursRemaining < 24) return 'critical';
  if (component === 'RBC' && hoursRemaining < 72) return 'warning';
  if (hoursRemaining < 48) return 'warning';
  return 'normal';
}

// Facility tier labels
export const TIER_LABELS: Record<string, string> = {
  national: 'Trung tâm Máu Quốc gia',
  regional: 'Trung tâm truyền máu khu vực',
  hospital: 'Bệnh viện (khoa HT-TM)',
  district: 'Trạm y tế / Phòng khám',
};