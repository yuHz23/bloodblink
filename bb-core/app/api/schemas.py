"""BB-Core — Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Facility ──────────────────────────────────────────────────

class FacilityOut(BaseModel):
    id: str
    name: str
    tier: str
    lat: float
    lon: float
    opt_in: bool = True
    safety_threshold: dict = {}
    h3_cell: Optional[str] = None    # ô lưới của cơ sở, dùng làm tâm tìm kiếm

    class Config:
        from_attributes = True


# ── Blood Unit ────────────────────────────────────────────────

class BloodUnitOut(BaseModel):
    id: str
    isbt_din: str
    component_code: str
    abo: str
    rh: str
    volume_ml: int
    collected_at: datetime
    expires_at: datetime
    status: str
    held_by_facility_id: str
    irradiated: bool = False
    leukoreduced: bool = False

    class Config:
        from_attributes = True


class InventoryQuery(BaseModel):
    """Query parameters for inventory listing."""
    component_code: Optional[str] = None
    abo: Optional[str] = None
    rh: Optional[str] = None
    facility_id: Optional[str] = None
    status: Optional[str] = "available"
    expires_before: Optional[datetime] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class HoursRemainingOut(BaseModel):
    """Blood unit with computed hours remaining before expiry."""
    unit: BloodUnitOut
    hours_remaining: float
    days_remaining: float
    urgency: str  # "expired" | "critical" | "warning" | "normal"


# ── Transfer Request ──────────────────────────────────────────

class TransferRequestIn(BaseModel):
    requester_facility_id: str
    component_code: str  # RBC, PLT, FFP, CRYO, WB
    abo: Optional[str] = None   # None = any compatible
    rh: Optional[str] = None
    qty: int = Field(default=1, ge=1)
    urgency: str = Field(default="routine")  # routine | urgent | emergency
    needed_by: datetime
    recipient_sex: Optional[str] = Field(default=None, pattern="^[MF]$")
    recipient_age: Optional[int] = Field(default=None, ge=0, le=120)


class TransferRequestOut(BaseModel):
    id: str
    requester_facility_id: str
    component_code: str
    abo: Optional[str]
    rh: Optional[str]
    qty: int
    urgency: str
    needed_by: datetime
    created_at: datetime
    state: str
    recipient_sex: Optional[str] = None
    recipient_age: Optional[int] = None

    class Config:
        from_attributes = True


class TransferOrderOut(BaseModel):
    id: str
    request_id: str
    source_facility_id: str
    unit_id: Optional[str] = None
    state: str
    approved_by: str
    at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TransferOfferResponseIn(BaseModel):
    accept: bool
    note: Optional[str] = Field(default=None, max_length=240)


class TransferOfferOut(BaseModel):
    id: str
    request_id: str
    source_facility_id: Optional[str] = None
    source_facility_name: str
    requester_facility_id: str
    requester_facility_name: str
    component_code: str
    abo: Optional[str] = None
    rh: Optional[str] = None
    qty: int
    urgency: str
    needed_by: datetime
    priority_rank: int
    available_qty: int
    offered_qty: int
    accepted_qty: int
    status: str
    created_at: datetime
    expires_at: datetime
    responded_at: Optional[datetime] = None
    response_note: Optional[str] = None


# ── Matching ──────────────────────────────────────────────────

class MatchRequest(BaseModel):
    """Request to find matching blood units for a transfer."""
    request_id: str


class MatchResultOut(BaseModel):
    """A ranked match with explanation."""
    unit_id: str
    rank: int
    score: float
    score_breakdown: dict
    reason_text: str
    eta_seconds: Optional[int] = None
    compatible: bool = True
    blocked_reason: Optional[str] = None

    class Config:
        from_attributes = True


class MatchResponse(BaseModel):
    request_id: str
    total_candidates: int
    compatible_count: int
    results: list[MatchResultOut]

    # Kho có đủ chưa, và có nên gọi người hiến không — xem services/sos_advice.py
    sos_action: str = "not_needed"        # required | advised | not_needed
    sos_reason: str = ""
    sos_urgency: Optional[str] = None     # mức khẩn đề nghị cho lời kêu gọi
    sos_target_count: int = 0
    sos_start_ring: int = 0
    sos_depleted_facilities: list[str] = []


# ── SOS ────────────────────────────────────────────────────────

class SOSEventIn(BaseModel):
    """
    Yêu cầu huy động người hiến.

    Trước đây schema này chỉ nhận (request_id, ring, target_count) nên payload
    của app BB-SOS luôn bị 422. Nay nhận đúng thứ app gửi — nhóm máu và chế phẩm
    là thông tin bắt buộc để server biết phải gọi ai.
    """
    facility_id: Optional[str] = None
    component_code: str = "WB"
    abo: Optional[str] = None            # nhóm máu người BỆNH cần
    rh: Optional[str] = None
    urgency: str = "urgent"              # routine | urgent | emergency
    qty: int = Field(default=1, ge=1)

    # Trường cũ — BB-Console vẫn dùng
    request_id: Optional[str] = None
    ring: int = Field(default=0, ge=0, le=3)
    target_count: Optional[int] = Field(default=None, ge=1)

    # Ô lưới H3 của cơ sở phát yêu cầu; bỏ trống thì lấy theo toạ độ facility
    h3_cell: Optional[str] = None


class SOSEventOut(BaseModel):
    id: str
    request_id: Optional[str] = None
    ring: int
    opened_at: datetime
    target_count: int
    accept_count: int = 0

    facility_id: Optional[str] = None
    component_code: Optional[str] = None
    abo: Optional[str] = None
    rh: Optional[str] = None
    urgency: Optional[str] = None

    # App BB-SOS đọc 3 trường này
    status: str = "open"
    message: str = ""
    donors_notified: int = 0

    class Config:
        from_attributes = True


class SOSRespondIn(BaseModel):
    """Phản hồi của người hiến — app gửi trong BODY, không phải query param."""
    donor_id: str
    response: Optional[str] = None       # tên trường phía app
    outcome: Optional[str] = None        # tên trường phía console

    # Chỉ gửi kèm khi NHẬN LỜI. Máy chủ bỏ qua nếu người hiến từ chối — không có
    # lý do gì giữ số điện thoại của người đã nói "không thể".
    contact_phone: Optional[str] = Field(default=None, max_length=32)
    contact_note: Optional[str] = Field(default=None, max_length=200)
    # Exact GPS is sent only after the donor explicitly accepts location sharing.
    share_location: Optional[bool] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)

    @property
    def resolved_outcome(self) -> str:
        return (self.outcome or self.response or "accepted").lower()


# ── Donor ──────────────────────────────────────────────────────

class DonorRegisterIn(BaseModel):
    """Đăng ký / cập nhật hồ sơ người hiến từ app BB-SOS."""
    id: Optional[str] = None             # UUID app tự sinh; bỏ trống thì server sinh
    # Bí mật thiết bị đã nhận ở lần đăng ký đầu. Bắt buộc khi `id` trỏ tới hồ sơ
    # đã tồn tại mà không kèm token còn hạn — nếu không thì ai cũng đăng ký đè
    # lên hồ sơ người khác và lấy được token của họ.
    device_secret: Optional[str] = None
    abo: str
    rh: str
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    sex: Optional[str] = None            # M | F
    weight_kg: Optional[int] = Field(default=None, ge=30, le=250)
    last_donation_at: Optional[datetime] = None

    # Vị trí — CHỈ ô lưới H3, không bao giờ nhận lat/lon
    h3_cell: Optional[str] = None
    geocell_ttl_hours: int = Field(default=4, ge=1, le=24)


class DonorGeocellIn(BaseModel):
    h3_cell: str
    ttl_hours: int = Field(default=4, ge=1, le=24)


class DonorDonationIn(BaseModel):
    component_code: str = "WB"
    donated_at: Optional[datetime] = None
    facility_id: Optional[str] = None


class DonorVerifyIn(BaseModel):
    verified: bool = True
    verified_by: Optional[str] = None    # mã cơ sở xác minh


class DonorOut(BaseModel):
    id: str
    abo: str
    rh: str
    blood_type: str
    verified: bool
    birth_year: Optional[int] = None
    sex: Optional[str] = None
    weight_kg: Optional[int] = None
    last_donation_at: Optional[datetime] = None

    geocell_h3: Optional[str] = None
    geocell_ttl: Optional[datetime] = None
    geocell_valid: bool = False

    days_since_donation: Optional[int] = None
    eligible: bool = True
    eligible_wb_rbc: bool = True
    eligible_plt_plasma: bool = True
    ineligible_reason: Optional[str] = None
    next_eligible_at: Optional[datetime] = None


# ── Auth ───────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    subject: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    facility_id: Optional[str] = None
    facility_name: Optional[str] = None


class MeOut(BaseModel):
    subject: str
    role: str
    facility_id: Optional[str] = None


class DonorRegisterOut(DonorOut):
    """
    Hồ sơ vừa đăng ký, kèm token của chính người hiến đó.

    App BB-SOS giữ token này để gọi các endpoint còn lại (làm mới ô lưới, ghi
    nhận lần hiến, trả lời SOS). Người hiến không có tài khoản mật khẩu.
    """
    access_token: str
    token_type: str = "bearer"
    expires_in: int

    # Chỉ có giá trị ở lần cấp đầu tiên — máy chủ chỉ giữ bản băm nên không cấp
    # lại được. App phải lưu ngay; mất là phải đăng ký hồ sơ mới.
    device_secret: Optional[str] = None


# ── Đẩy thông báo (P2) ─────────────────────────────────────────

class DonorPushTokenIn(BaseModel):
    """Địa chỉ nhận thông báo của thiết bị. Gửi rỗng nghĩa là gỡ đăng ký."""
    push_token: Optional[str] = None
    platform: Optional[str] = None       # android | ios


class SOSNotificationOut(BaseModel):
    id: str
    sos_event_id: str
    donor_id: str
    ring: int
    created_at: datetime
    channel: str
    status: str                          # pending | sent | failed | read
    error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SOSInboxItem(BaseModel):
    """
    Một lời kêu gọi đang chờ người hiến trả lời.

    Gộp sẵn thông tin của sự kiện để app dựng được màn hình SOS chỉ với một lần
    gọi — điện thoại đang cấp cứu thì không nên phải gọi thêm vòng nữa.
    """
    notification_id: str
    event_id: str
    ring: int
    notified_at: datetime
    status: str

    abo: Optional[str] = None
    rh: Optional[str] = None
    blood_type: Optional[str] = None
    component_code: Optional[str] = None
    urgency: Optional[str] = None
    target_count: int = 1
    accept_count: int = 0
    event_status: str = "open"
    opened_at: Optional[datetime] = None
    facility_id: Optional[str] = None
    facility_name: Optional[str] = None

    title: str = ""
    body: str = ""
    reward_role: Optional[str] = None
    reward_status: Optional[str] = None
    reward_amount_vnd: Optional[int] = None


# ── Ghi vết & danh tính (P4) ───────────────────────────────────

class SOSResponderOut(BaseModel):
    """
    Người hiến đã nhận lời, kèm cách liên hệ họ tự cung cấp.

    Chỉ cơ sở phát lời kêu gọi (hoặc quản trị) đọc được, và mỗi lần đọc đều để
    lại một dòng trong nhật ký ghi vết.
    """
    donor_id: str
    blood_type: Optional[str] = None
    outcome: str
    responded_at: datetime
    contact_phone: Optional[str] = None
    contact_note: Optional[str] = None
    location_sharing_consented: Optional[bool] = None


class SOSResponderLocationOut(BaseModel):
    """Precise locations explicitly shared for one active SOS, without donor identity."""
    latitude: float
    longitude: float
    shared_at: datetime


class SOSRewardSelectIn(BaseModel):
    primary_donor_id: str


class SOSRewardChoiceIn(BaseModel):
    choice: str = Field(pattern="^(continue|decline)$")


class SOSRewardDonationIn(BaseModel):
    donated: bool


class SOSRewardOut(BaseModel):
    id: str
    sos_event_id: str
    donor_id: str
    role: str
    status: str
    proposed_amount_vnd: Optional[int] = None
    created_at: datetime
    decision_at: Optional[datetime] = None
    donation_confirmed_at: Optional[datetime] = None
    donation_confirmed_by: Optional[str] = None

    class Config:
        from_attributes = True


class AuditEntryOut(BaseModel):
    id: str
    at: datetime
    actor: str
    action: str
    payload: dict = {}
    hash: str
    prev_hash: Optional[str] = None


class AuditVerifyOut(BaseModel):
    ok: bool
    checked: int
    total: int
    reason: str
    head_hash: Optional[str] = None
    broken_at: Optional[str] = None
