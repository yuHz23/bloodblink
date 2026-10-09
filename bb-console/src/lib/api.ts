/**
 * BB-Console — API client for BB-Core backend.
 * All endpoints match the FastAPI router definitions.
 */

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';

// ── Token ──────────────────────────────────────────────────────
// Mọi endpoint trừ /health, /spec-summary, /auth/login và /donors/register đều
// đòi Bearer token kể từ P1.

const TOKEN_KEY = 'bb_token';

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token: string) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* chế độ riêng tư */ }
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* chế độ riêng tư */ }
}

/** Phiên hết hạn giữa chừng — App lắng nghe để đưa về màn đăng nhập. */
export const AUTH_EXPIRED_EVENT = 'bb:auth-expired';

async function fetchJSON<T>(path: string, opts?: RequestInit): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        'Bypass-Tunnel-Reminder': 'true',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...opts?.headers,
      },
      ...opts,
    });
  } catch {
    throw new Error(`Không kết nối được backend tại ${API_BASE}. Hãy mở bb-core local ở cổng 8000 và dùng console local.`);
  }
  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────

export interface Facility {
  id: string;
  name: string;
  tier: string;
  lat: number;
  lon: number;
  opt_in: boolean;
  safety_threshold: Record<string, number>;
  h3_cell: string | null;      // ô lưới của cơ sở, dùng làm tâm tìm kiếm
}

// ── Auth ───────────────────────────────────────────────────────

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: string;
  subject: string;
  username: string | null;
  full_name: string | null;
  facility_id: string | null;
  facility_name: string | null;
}

// ── Donor ──────────────────────────────────────────────────────

export interface Donor {
  id: string;
  abo: string;
  rh: string;
  blood_type: string;
  verified: boolean;
  birth_year: number | null;
  sex: string | null;
  weight_kg: number | null;
  last_donation_at: string | null;
  geocell_h3: string | null;
  geocell_ttl: string | null;
  geocell_valid: boolean;
  days_since_donation: number | null;
  eligible: boolean;
  eligible_wb_rbc: boolean;
  eligible_plt_plasma: boolean;
  ineligible_reason: string | null;
  next_eligible_at: string | null;
}

/**
 * Người hiến trong kết quả `/sos/donors/nearby`.
 *
 * Endpoint này trả `donor_id`, KHÔNG phải `id` như `/donors` — dùng nhầm kiểu
 * thì cột mã hiện rỗng và nút xác minh gọi vào `/donors/undefined/verify`.
 */
export interface NearbyDonor {
  donor_id: string;
  abo: string;
  rh: string;
  blood_type: string;
  h3_cell: string | null;
  verified: boolean;
  reachable_by_push: boolean;
  days_since_donation: number | null;
  eligible: boolean;
  eligible_wb_rbc: boolean;
  eligible_plt_plasma: boolean;
  ineligible_reason: string | null;
  next_eligible_at: string | null;
}

export interface NearbyDonorsResult {
  h3_cell: string;
  ring: number;
  component_code: string;
  cells_searched: string[] | null;
  citywide: boolean;
  donors_found: number;
  total_donors: number;
  donors: NearbyDonor[];
}

/** Tồn kho của một cơ sở, cho MỘT nhóm máu và MỘT chế phẩm. */
export interface FacilityStock {
  facility_id: string;
  abo: string;
  rh: string;
  blood_type: string;      // "O+", "AB-"…
  component: string;
  count: number;
}

/** Một ô lưới H3 kèm số người hiến trong đó — KHÔNG có mã người hiến nào. */
export interface DensityCell {
  h3_cell: string;
  lat: number;
  lon: number;
  count: number;
  boundary: [number, number][];   // ranh giới ô, để vẽ đa giác
}

export interface DonorDensity {
  cells: DensityCell[];
  min_donors: number;        // ngưỡng k-ẩn danh đang áp
  suppressed_cells: number;  // số ô bị ẩn vì dưới ngưỡng
  resolution: number;
}

/** Một dòng nhật ký ghi vết. `hash` băm cả `prev_hash` nên sửa giữa chừng là gãy chuỗi. */
export interface AuditEntry {
  id: string;
  at: string;
  actor: string;               // mã tài khoản hoặc mã người hiến, KHÔNG phải họ tên
  action: string;              // auth.login | donor.search | sos.open | …
  payload: Record<string, unknown>;
  hash: string;
  prev_hash: string | null;
}

export interface AuditVerify {
  ok: boolean;
  checked: number;
  total: number;
  reason: string;
  head_hash: string | null;
  broken_at: string | null;    // mã dòng hỏng đầu tiên
}

export interface SosNotification {
  id: string;
  sos_event_id: string;
  donor_id: string;
  ring: number;
  created_at: string;
  channel: string;
  status: string;             // pending | sent | failed | read
  error: string | null;
  delivered_at: string | null;
  read_at: string | null;
}

/** Người hiến đã nhận lời — điểm duy nhất hệ thống lộ ra cách liên hệ. */
export interface SosResponder {
  donor_id: string;
  blood_type: string | null;
  outcome: string;
  responded_at: string;
  contact_phone: string | null;
  contact_note: string | null;
  location_sharing_consented?: boolean | null;
}

/** Aggregate location of donors who accepted an SOS; no donor ID or contact details. */
export interface AcceptedDonorCell {
  h3_cell: string;
  lat: number;
  lon: number;
  count: number;
}

export interface SharedResponderLocation {
  latitude: number;
  longitude: number;
  shared_at: string;
}

export interface SosReward {
  id: string;
  sos_event_id: string;
  donor_id: string;
  role: 'primary' | 'backup';
  status: 'awaiting_donation' | 'awaiting_choice' | 'compensation_proposed' | 'mock_ready' | 'not_completed';
  proposed_amount_vnd: number | null;
  created_at: string;
  decision_at: string | null;
  donation_confirmed_at: string | null;
  donation_confirmed_by: string | null;
}

export interface SosEvent {
  id: string;
  request_id?: string | null;
  ring: number;
  opened_at: string;
  target_count: number;
  accept_count: number;
  facility_id: string | null;
  component_code: string | null;
  abo: string | null;
  rh: string | null;
  urgency: string | null;
  status: string;
  message: string;
  donors_notified: number;
}

export interface BloodUnit {
  id: string;
  isbt_din: string;
  component_code: string;
  abo: string;
  rh: string;
  volume_ml: number;
  collected_at: string;
  expires_at: string;
  status: string;
  held_by_facility_id: string;
  irradiated: boolean;
  leukoreduced: boolean;
}

export interface HoursRemaining {
  unit: BloodUnit;
  hours_remaining: number;
  days_remaining: number;
  urgency: 'expired' | 'critical' | 'warning' | 'normal';
}

export interface InventorySummary {
  by_component_status: { component: string; status: string; count: number }[];
  by_blood_type: { abo: string; rh: string; count: number }[];
  by_facility_component: { facility_id: string; component: string; count: number }[];
  expiring_within_24h: number;
  expiring_within_72h: number;
  total_available: number;
}

export interface TransferRequest {
  id: string;
  requester_facility_id: string;
  component_code: string;
  abo: string | null;
  rh: string | null;
  qty: number;
  urgency: string;
  needed_by: string;
  created_at: string;
  state: string;
  recipient_sex: string | null;
  recipient_age: number | null;
}

export interface TransferOrder {
  id: string;
  request_id: string;
  source_facility_id: string;
  unit_id: string | null;
  state: string;
  approved_by: string;
  at: string;
  completed_at: string | null;
}

export interface TransferOffer {
  id: string;
  request_id: string;
  source_facility_id: string | null;
  source_facility_name: string;
  requester_facility_id: string;
  requester_facility_name: string;
  component_code: string;
  abo: string | null;
  rh: string | null;
  qty: number;
  urgency: string;
  needed_by: string;
  priority_rank: number;
  available_qty: number;
  offered_qty: number;
  accepted_qty: number;
  status: 'pending' | 'accepted' | 'declined' | 'expired' | 'cancelled' | 'no_source';
  created_at: string;
  expires_at: string;
  responded_at: string | null;
  response_note: string | null;
}

export interface MatchResult {
  unit_id: string;
  rank: number;
  score: number;
  score_breakdown: Record<string, number>;
  reason_text: string;
  eta_seconds: number | null;
  compatible: boolean;
  blocked_reason: string | null;
}

export interface MatchResponse {
  request_id: string;
  total_candidates: number;
  compatible_count: number;
  results: MatchResult[];

  /** Kho có đủ chưa, và có nên gọi người hiến không. Xem services/sos_advice.py.
   *  required = phải gọi · advised = nên gọi để bù · not_needed = thôi. */
  sos_action: 'required' | 'advised' | 'not_needed';
  sos_reason: string;
  sos_urgency: string | null;
  sos_target_count: number;
  sos_start_ring: number;
  sos_depleted_facilities: string[];
}

// ── Routing types ────────────────────────────────────────────────

export interface RouteEta {
  from: { lat: number; lon: number };
  to: { lat: number; lon: number };
  mode: string;
  distance_m: number;
  duration_s: number;
  duration_min: number;
  provider: string;
  routing_mode: string;
  geometry?: [number, number][] | null;
}

export interface EtaComparison {
  straight_line: { distance_m: number; duration_s: number; duration_min: number; provider: string };
  road: { distance_m: number; duration_s: number; duration_min: number; provider: string };
  difference: { extra_seconds: number; extra_minutes: number; percentage: number };
}

export interface HcmcPairComparison {
  pairs: {
    from: { id: string; name: string };
    to: { id: string; name: string };
    straight_line: { distance_m: number; duration_s: number; duration_min: number; provider: string };
    road: { distance_m: number; duration_s: number; duration_min: number; provider: string };
    difference: { extra_seconds: number; extra_minutes: number; percentage: number };
  }[];
  summary: {
    total_pairs: number;
    avg_straight_line_min: number;
    avg_road_min: number;
    avg_extra_time_pct: number;
    note: string;
  };
}

export interface FacilityEtaResult {
  from_facility_id: string;
  from_name: string;
  to_facilities: {
    to_facility_id: string;
    to_name: string;
    distance_m: number;
    duration_s: number;
    duration_min: number;
    provider: string;
  }[];
}

// ── API calls ──────────────────────────────────────────────────

export const api = {
  // Health
  health: () => fetchJSON<{ status: string; service: string; version: string }>('/health'),
  specSummary: () => fetchJSON<Record<string, unknown>>('/spec-summary'),

  // Auth
  login: (username: string, password: string) =>
    fetchJSON<LoginResult>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  me: () => fetchJSON<{ subject: string; role: string; facility_id: string | null }>('/auth/me'),

  // Facilities
  listFacilities: () => fetchJSON<Facility[]>('/facilities'),

  // Donors
  listDonors: (params: {
    abo?: string; rh?: string; verified_only?: boolean; with_geocell?: boolean;
    component_code?: string; eligible_only?: boolean; limit?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '') qs.set(k, String(v));
    });
    return fetchJSON<Donor[]>(`/donors?${qs}`);
  },

  getDonor: (donorId: string, componentCode?: string) =>
    fetchJSON<Donor>(`/donors/${donorId}${componentCode ? `?component_code=${componentCode}` : ''}`),

  verifyDonor: (donorId: string, verified: boolean, verifiedBy?: string) =>
    fetchJSON<Donor>(`/donors/${donorId}/verify`, {
      method: 'POST',
      body: JSON.stringify({ verified, verified_by: verifiedBy }),
    }),

  // Inventory
  listInventory: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return fetchJSON<BloodUnit[]>(`/inventory/${qs}`);
  },

  listExpiring: (withinHours = 48, component?: string, facilityId?: string, limit = 50) => {
    const params = new URLSearchParams({ within_hours: String(withinHours) });
    if (component) params.set('component', component);
    if (facilityId) params.set('facility_id', facilityId);
    params.set('limit', String(limit));
    return fetchJSON<HoursRemaining[]>(`/inventory/expiring?${params}`);
  },

  inventorySummary: () => fetchJSON<InventorySummary>('/inventory/summary'),

  // Matching
  createTransferRequest: (data: {
    requester_facility_id: string;
    component_code: string;
    abo?: string;
    rh?: string;
    qty?: number;
    urgency?: string;
    needed_by: string;
    recipient_sex?: string;
    recipient_age?: number;
  }) => fetchJSON<TransferRequest>('/matching/request', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  findMatches: (requestId: string) =>
    fetchJSON<MatchResponse>(`/matching/find?request_id=${requestId}`, { method: 'POST' }),

  broadcastTransferRequest: (requestId: string, responseWindowMinutes: number) =>
    fetchJSON<TransferOffer[]>(`/matching/request/${requestId}/broadcast?response_window_minutes=${responseWindowMinutes}`, { method: 'POST' }),

  listTransferOffers: (requestId: string) =>
    fetchJSON<TransferOffer[]>(`/matching/request/${requestId}/offers`),

  listIncomingTransferOffers: (facilityId?: string) => {
    const query = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
    return fetchJSON<TransferOffer[]>(`/matching/offers/incoming${query}`);
  },

  respondToTransferOffer: (offerId: string, accept: boolean, facilityId?: string) => {
    const query = facilityId ? `?facility_id=${encodeURIComponent(facilityId)}` : '';
    return fetchJSON<TransferOffer>(`/matching/offers/${offerId}/respond${query}`, {
      method: 'POST', body: JSON.stringify({ accept }),
    });
  },

  getTransferRequest: (requestId: string) =>
    fetchJSON<TransferRequest>(`/matching/request/${requestId}`),

  listTransferOrders: (requestId: string) =>
    fetchJSON<TransferOrder[]>(`/matching/request/${requestId}/orders`),

  approveTransfer: (requestId: string, approvedBy: string) =>
    fetchJSON<TransferRequest>(`/matching/request/${requestId}/approve?approved_by=${encodeURIComponent(approvedBy)}`, { method: 'POST' }),

  completeTransferOrder: (orderId: string, receivedBy = 'console-user') =>
    fetchJSON<TransferOrder>(`/matching/order/${orderId}/complete?received_by=${encodeURIComponent(receivedBy)}`, { method: 'POST' }),

  // SOS
  findNearbyDonors: (opts: {
    h3Cell: string; abo?: string; rh?: string; componentCode?: string;
    ring?: number; verifiedOnly?: boolean; eligibleOnly?: boolean; limit?: number;
  }) => {
    const params = new URLSearchParams({ h3_cell: opts.h3Cell });
    if (opts.abo) params.set('abo', opts.abo);
    if (opts.rh) params.set('rh', opts.rh);
    if (opts.componentCode) params.set('component_code', opts.componentCode);
    if (opts.ring !== undefined) params.set('ring', String(opts.ring));
    if (opts.verifiedOnly !== undefined) params.set('verified_only', String(opts.verifiedOnly));
    if (opts.eligibleOnly !== undefined) params.set('eligible_only', String(opts.eligibleOnly));
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));
    return fetchJSON<NearbyDonorsResult>(`/sos/donors/nearby?${params}`);
  },

  createSosEvent: (data: {
    facility_id?: string; component_code: string; abo?: string; rh?: string;
    urgency?: string; qty?: number; ring?: number; h3_cell?: string; request_id?: string;
  }) => fetchJSON<SosEvent>('/sos/event', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  respondToSosEvent: (eventId: string, data: {
    donor_id: string;
    outcome: 'accepted' | 'declined';
    share_location?: boolean;
    latitude?: number;
    longitude?: number;
  }) => fetchJSON<{
    status: string;
    event_id: string;
    donor_id: string;
    outcome: 'accepted' | 'declined' | 'no_show';
    accept_count: number;
    target_count: number;
    event_status: string;
    location_sharing_consented: boolean | null;
  }>(`/sos/event/${eventId}/respond`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  getSosEvent: (eventId: string) => fetchJSON<SosEvent>(`/sos/event/${eventId}`),

  completeSosEvent: (eventId: string) =>
    fetchJSON<SosEvent>(`/sos/event/${eventId}/complete`, { method: 'POST' }),

  /** Nâng vòng trên CHÍNH sự kiện đó — không tạo sự kiện mới, không gọi lại
   *  người đã được gọi ở vòng trước. */
  escalateSosEvent: (eventId: string) =>
    fetchJSON<SosEvent>(`/sos/event/${eventId}/escalate`, { method: 'POST' }),

  listSosNotifications: (eventId: string) =>
    fetchJSON<SosNotification[]>(`/sos/event/${eventId}/notifications`),

  /** Mỗi lần gọi để lại một dòng trong nhật ký ghi vết. */
    listSosResponders: (eventId: string) =>
      fetchJSON<SosResponder[]>(`/sos/event/${eventId}/responses`),

    /// Vị trí H3 tổng hợp của người hiến đã nhận lời; không trả mã hay thông tin liên hệ.
    listAcceptedDonorCells: () => fetchJSON<AcceptedDonorCell[]>('/sos/responders/map'),

  listSosResponderLocations: (eventId: string) =>
    fetchJSON<SharedResponderLocation[]>(`/sos/event/${eventId}/locations`),

  listSosRewards: (eventId: string) =>
    fetchJSON<SosReward[]>(`/sos/event/${eventId}/rewards`),

  selectSosRewardRecipients: (eventId: string, primaryDonorId: string) =>
    fetchJSON<SosReward[]>(`/sos/event/${eventId}/rewards/select`, {
      method: 'POST', body: JSON.stringify({ primary_donor_id: primaryDonorId }),
    }),

  chooseSosBackup: (eventId: string, donorId: string, choice: 'continue' | 'decline') =>
    fetchJSON<SosReward>(`/sos/event/${eventId}/rewards/${donorId}/choice`, {
      method: 'POST', body: JSON.stringify({ choice }),
    }),

  confirmSosDonation: (eventId: string, donorId: string, donated = true) =>
    fetchJSON<SosReward>(`/sos/event/${eventId}/rewards/${donorId}/donation`, {
      method: 'POST', body: JSON.stringify({ donated }),
    }),

  /// Tồn kho theo CƠ SỞ × NHÓM MÁU — dữ liệu tô bản đồ. Chỉ đếm đơn vị còn hạn.
  inventoryByFacility: (componentCode?: string) =>
    fetchJSON<FacilityStock[]>(
      `/inventory/by-facility${componentCode ? `?component_code=${componentCode}` : ''}`),

  /// Mật độ người hiến theo ô lưới H3. KHÔNG có mã người hiến — chỉ số đếm.
  donorDensity: (opts: { abo?: string; rh?: string; minDonors?: number } = {}) => {
    const p = new URLSearchParams();
    if (opts.abo) p.set('abo', opts.abo);
    if (opts.rh) p.set('rh', opts.rh);
    p.set('min_donors', String(opts.minDonors ?? 3));
    return fetchJSON<DonorDensity>(`/sos/donors/density?${p}`);
  },

  /// Danh sách SOS đang mở — để chấm nhu cầu lên bản đồ.
  listOpenSosEvents: () => fetchJSON<SosEvent[]>('/sos/events?status=open'),

  /// Các ca SOS mới nhất, gồm cả ca đã đủ người để admin xác nhận hiến.
  listSosEvents: () => fetchJSON<SosEvent[]>('/sos/events?limit=50'),

  // Nhật ký ghi vết (P4) — CHỈ vai trò admin đọc được.
  listAudit: (opts: { action?: string; actor?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.action) params.set('action', opts.action);
    if (opts.actor) params.set('actor', opts.actor);
    params.set('limit', String(opts.limit ?? 200));
    return fetchJSON<AuditEntry[]>(`/audit?${params}`);
  },

  /** Chuỗi băm còn liền mạch không — trả về dòng hỏng đầu tiên nếu có. */
  verifyAudit: () => fetchJSON<AuditVerify>('/audit/verify'),

  // Routing
  getEta: (fromLat: number, fromLon: number, toLat: number, toLon: number, mode = 'car') =>
    fetchJSON<RouteEta>(`/routing/eta?from_lat=${fromLat}&from_lon=${fromLon}&to_lat=${toLat}&to_lon=${toLon}&mode=${mode}`),

  compareEta: (fromLat: number, fromLon: number, toLat: number, toLon: number) =>
    fetchJSON<EtaComparison>(`/routing/eta/compare?from_lat=${fromLat}&from_lon=${fromLon}&to_lat=${toLat}&to_lon=${toLon}`),

  compareHcmcPairs: () => fetchJSON<HcmcPairComparison>('/routing/eta/hcmc-pairs'),

  getEtaFromFacility: (facilityId: string) =>
    fetchJSON<FacilityEtaResult>(`/routing/eta/facility/${facilityId}`),

  setRoutingProvider: (provider: string, osrmUrl?: string) =>
    fetchJSON<{ provider: string; url?: string }>(`/routing/set-provider?provider=${provider}${osrmUrl ? '&osrm_url=' + encodeURIComponent(osrmUrl) : ''}`, { method: 'POST' }),
};
