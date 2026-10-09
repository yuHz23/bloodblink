"""
BB-Core — Core database models
Maps directly from the data model spec in the planning doc.

Two architectural constraints baked into the schema:
1. NO patient medical data stored — only indexes and request codes.
2. `donor` stores H3 geocell (~1 km) with TTL, NOT raw coordinates.
"""

from datetime import datetime, date, timedelta, timezone
from enum import Enum as PyEnum
import hashlib

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date, ForeignKey,
    Text, Index, CheckConstraint, Enum, Numeric, BigInteger, UniqueConstraint
)
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship
from geoalchemy2 import Geometry


def utcnow() -> datetime:
    """
    Mốc thời gian CÓ múi giờ.

    Toàn bộ tầng API dùng `datetime.now(timezone.utc)`; nếu cột là TIMESTAMP
    không múi giờ thì asyncpg từ chối thẳng ("can't subtract offset-naive and
    offset-aware datetimes") và cả seed lẫn API đều hỏng. Vì vậy mọi cột thời
    gian dưới đây đều là `DateTime(timezone=True)` và mặc định lấy hàm này,
    thay cho `datetime.utcnow` (trả về giá trị không múi giờ, đã lỗi thời).
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────

class ComponentCode(PyEnum):
    WB   = "WB"     # Whole blood
    RBC  = "RBC"    # Red blood cells
    PLT  = "PLT"    # Platelets
    FFP  = "FFP"    # Fresh frozen plasma
    CRYO = "CRYO"   # Cryoprecipitate


class ABO(PyEnum):
    O  = "O"
    A  = "A"
    B  = "B"
    AB = "AB"


class RhD(PyEnum):
    POS = "+"
    NEG = "-"


class UnitStatus(PyEnum):
    AVAILABLE  = "available"
    RESERVED   = "reserved"
    IN_TRANSIT  = "in_transit"
    ISSUED      = "issued"
    DISCARDED   = "discarded"
    EXPIRED     = "expired"


class FacilityTier(PyEnum):
    NATIONAL   = "national"    # Trung tâm Máu Quốc gia
    REGIONAL   = "regional"    # Trung tâm truyền máu khu vực
    HOSPITAL   = "hospital"   # Bệnh viện có khoa huyết học – truyền máu
    DISTRICT   = "district"   # Trạm y tế / phòng khám có kho máu


class RequestUrgency(PyEnum):
    ROUTINE    = "routine"       # Luân chuyển chủ động
    URGENT     = "urgent"        # Cần trong 6 giờ
    EMERGENCY  = "emergency"    # Cấp cứu — cần trong 2 giờ


class TransferState(PyEnum):
    PENDING    = "pending"
    MATCHED    = "matched"
    APPROVED   = "approved"
    IN_TRANSIT  = "in_transit"
    DELIVERED  = "delivered"
    CANCELLED  = "cancelled"


# ── Tables ─────────────────────────────────────────────────────

class Facility(Base):
    """Cơ sở y tế có kho máu hoặc khoa huyết học – truyền máu."""
    __tablename__ = "facility"

    id            = Column(String, primary_key=True)  # UUID
    name          = Column(String, nullable=False)
    tier          = Column(Enum(FacilityTier), nullable=False)
    geom          = Column(Geometry("POINT", srid=4326), nullable=False)
    opt_in        = Column(Boolean, default=True, nullable=False)  # bật chia sẻ
    safety_threshold_json = Column(JSONB, default={}, nullable=False)
    # e.g. {"RBC": 20, "PLT": 10} — minimum stock before refusing to share

    # Relationships
    blood_units   = relationship("BloodUnit", back_populates="held_by", foreign_keys="BloodUnit.held_by_facility_id")
    transfer_requests = relationship("TransferRequest", back_populates="requester", foreign_keys="TransferRequest.requester_facility_id")
    transfer_orders = relationship("TransferOrder", back_populates="source", foreign_keys="TransferOrder.source_facility_id")

    __table_args__ = (
        Index("ix_facility_geom", geom, postgresql_using="gist"),
    )


class BloodUnit(Base):
    """Đơn vị chế phẩm máu — tracked by ISBT 128 DIN."""
    __tablename__ = "blood_unit"

    id                  = Column(String, primary_key=True)
    isbt_din            = Column(String, unique=True, nullable=False)  # ISBT 128 Donation Identification Number
    component_code      = Column(Enum(ComponentCode), nullable=False)
    abo                 = Column(Enum(ABO), nullable=False)
    rh                  = Column(Enum(RhD), nullable=False)
    volume_ml           = Column(Integer, nullable=False)
    collected_at        = Column(DateTime(timezone=True), nullable=False)
    expires_at          = Column(DateTime(timezone=True), nullable=False)
    status              = Column(Enum(UnitStatus), default=UnitStatus.AVAILABLE, nullable=False)
    held_by_facility_id = Column(String, ForeignKey("facility.id"), nullable=False)
    irradiated          = Column(Boolean, default=False)
    leukoreduced        = Column(Boolean, default=False)

    # Relationships
    held_by         = relationship("Facility", back_populates="blood_units", foreign_keys=[held_by_facility_id])
    inventory_events = relationship("InventoryEvent", back_populates="unit")
    transfer_candidates = relationship("TransferCandidate", back_populates="unit")

    __table_args__ = (
        Index("ix_blood_unit_component_abo_rh", component_code, abo, rh),
        Index("ix_blood_unit_expires", expires_at),
        Index("ix_blood_unit_facility_status", held_by_facility_id, status),
        Index("ix_blood_unit_status_expires", status, expires_at),
    )


class InventoryEvent(Base):
    """Nhật ký sự kiện tồn kho — mọi thay đổi trạng thái được ghi lại."""
    __tablename__ = "inventory_event"

    id          = Column(String, primary_key=True)
    unit_id     = Column(String, ForeignKey("blood_unit.id"), nullable=False)
    event_type  = Column(String, nullable=False)  # received|reserved|issued|discarded|expired|transferred_out|transferred_in
    at          = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor_id    = Column(String, nullable=True)    # user or system
    note        = Column(Text, nullable=True)

    # Relationships
    unit = relationship("BloodUnit", back_populates="inventory_events")

    __table_args__ = (
        Index("ix_inventory_event_unit_at", unit_id, at),
    )


class TransferRequest(Base):
    """Yêu cầu điều chuyển chế phẩm máu."""
    __tablename__ = "transfer_request"

    id                    = Column(String, primary_key=True)
    requester_facility_id = Column(String, ForeignKey("facility.id"), nullable=False)
    component_code        = Column(Enum(ComponentCode), nullable=False)
    abo                   = Column(Enum(ABO), nullable=True)   # null = any compatible
    rh                    = Column(Enum(RhD), nullable=True)
    qty                   = Column(Integer, nullable=False, default=1)
    urgency               = Column(Enum(RequestUrgency), default=RequestUrgency.ROUTINE)
    needed_by             = Column(DateTime(timezone=True), nullable=False)
    created_at            = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    state                 = Column(Enum(TransferState), default=TransferState.PENDING)
    recipient_sex         = Column(String(1), nullable=True)
    recipient_age         = Column(Integer, nullable=True)

    # Relationships
    requester  = relationship("Facility", back_populates="transfer_requests", foreign_keys=[requester_facility_id])
    candidates = relationship("TransferCandidate", back_populates="request", order_by="TransferCandidate.rank")
    orders     = relationship("TransferOrder", back_populates="request", order_by="TransferOrder.at")

    __table_args__ = (
        Index("ix_transfer_request_state_created", state, created_at),
    )


class TransferCandidate(Base):
    """Đơn vị chế phẩm được ghép nguồn và xếp hạng — mỗi dòng kèm giải thích."""
    __tablename__ = "transfer_candidate"

    id                = Column(String, primary_key=True)
    request_id        = Column(String, ForeignKey("transfer_request.id"), nullable=False)
    unit_id           = Column(String, ForeignKey("blood_unit.id"), nullable=False)
    rank               = Column(Integer, nullable=False)
    score              = Column(Float, nullable=False)
    score_breakdown    = Column(JSONB, nullable=False)  # {"urgency_expiry": 0.8, "time_margin": 0.6, ...}
    reason_text        = Column(Text, nullable=False)    # human-readable explanation
    eta_seconds        = Column(Integer, nullable=True)  # estimated travel time
    compatible         = Column(Boolean, default=False, nullable=False)
    blocked_reason     = Column(Text, nullable=True)

    # Relationships
    request = relationship("TransferRequest", back_populates="candidates")
    unit    = relationship("BloodUnit", back_populates="transfer_candidates")


class TransferOffer(Base):
    """A ranked, time-limited hospital invitation to support a transfer request."""
    __tablename__ = "transfer_offer"

    id                 = Column(String, primary_key=True)
    request_id         = Column(String, ForeignKey("transfer_request.id"), nullable=False)
    source_facility_id = Column(String, ForeignKey("facility.id"), nullable=True)
    priority_rank      = Column(Integer, nullable=False)
    available_qty      = Column(Integer, nullable=False, default=0)
    offered_qty        = Column(Integer, nullable=False, default=1)
    accepted_qty       = Column(Integer, nullable=False, default=0)
    status             = Column(String(16), nullable=False, default="pending")
    created_at         = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at         = Column(DateTime(timezone=True), nullable=False)
    responded_at       = Column(DateTime(timezone=True), nullable=True)
    response_note      = Column(Text, nullable=True)

    request = relationship("TransferRequest")
    source = relationship("Facility")

    __table_args__ = (
        UniqueConstraint("request_id", "source_facility_id", name="uq_transfer_offer_request_source"),
        Index("ix_transfer_offer_source_status", source_facility_id, status),
        Index("ix_transfer_offer_request_status", request_id, status),
    )


class TransferOrder(Base):
    """Lệnh điều chuyển đã được duyệt."""
    __tablename__ = "transfer_order"

    id                  = Column(String, primary_key=True)
    request_id          = Column(String, ForeignKey("transfer_request.id"), nullable=False)
    source_facility_id  = Column(String, ForeignKey("facility.id"), nullable=False)
    unit_id             = Column(String, ForeignKey("blood_unit.id"), nullable=True)
    state               = Column(Enum(TransferState), default=TransferState.APPROVED)
    approved_by         = Column(String, nullable=False)
    at                  = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at        = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    request  = relationship("TransferRequest", back_populates="orders")
    source   = relationship("Facility", back_populates="transfer_orders", foreign_keys=[source_facility_id])
    shipment = relationship("Shipment", back_populates="order", uselist=False)


class FacilitySupportContribution(Base):
    """Confirmed blood transfers used to apply reciprocal matching priority."""
    __tablename__ = "facility_support_contribution"

    id                    = Column(String, primary_key=True)
    transfer_order_id     = Column(String, ForeignKey("transfer_order.id"), nullable=False, unique=True)
    request_id            = Column(String, ForeignKey("transfer_request.id"), nullable=False)
    unit_id               = Column(String, ForeignKey("blood_unit.id"), nullable=False)
    supporter_facility_id = Column(String, ForeignKey("facility.id"), nullable=False)
    beneficiary_facility_id = Column(String, ForeignKey("facility.id"), nullable=False)
    component_code        = Column(Enum(ComponentCode), nullable=False)
    quantity              = Column(Integer, nullable=False, default=1)
    at                    = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_support_reciprocity", supporter_facility_id, beneficiary_facility_id, at),
        Index("ix_support_beneficiary", beneficiary_facility_id, at),
    )


class Shipment(Base):
    """Lô vận chuyển — liên kết với BB-Box."""
    __tablename__ = "shipment"

    id              = Column(String, primary_key=True)
    order_id        = Column(String, ForeignKey("transfer_order.id"), nullable=False)
    box_id          = Column(String, nullable=True)  # BB-Box hardware ID
    departed_at     = Column(DateTime(timezone=True), nullable=True)
    arrived_at      = Column(DateTime(timezone=True), nullable=True)
    excursion_flag  = Column(Boolean, default=False)  # true if temp went out of range

    # Relationships
    order    = relationship("TransferOrder", back_populates="shipment")
    readings = relationship("ShipmentReading", back_populates="shipment")


class ShipmentReading(Base):
    """
    Đọc nhiệt độ BB-Box — TimescaleDB hypertable.
    Two thresholds: storage mode vs transport mode (Art 20 TT 26/2013/TT-BYT).
    """
    __tablename__ = "shipment_reading"

    time      = Column(DateTime(timezone=True), primary_key=True)
    box_id    = Column(String, primary_key=True)
    t_core    = Column(Numeric(5, 2), nullable=False)   # core sensor (TMP117)
    t_shell   = Column(Numeric(5, 2), nullable=False)   # shell sensor
    lid_open  = Column(Boolean, default=False)           # reed switch
    shock_g   = Column(Numeric(4, 2), nullable=True)    # LIS3DH peak g-force
    shipment_id = Column(String, ForeignKey("shipment.id"), nullable=True)

    # Relationships
    shipment = relationship("Shipment", back_populates="readings")

    __table_args__ = (
        # TimescaleDB: convert to hypertable in migration
        Index("ix_reading_time_box", time, box_id),
    )


class Donor(Base):
    """
    Người hiến máu — ô lưới H3 với thời hạn sống, KHÔNG lưu tọa độ thô.
    """
    __tablename__ = "donor"

    id                = Column(String, primary_key=True)
    abo               = Column(Enum(ABO), nullable=False)
    rh                = Column(Enum(RhD), nullable=False)
    last_donation_at  = Column(DateTime(timezone=True), nullable=True)
    verified          = Column(Boolean, default=False, nullable=False)
    geocell_h3        = Column(String, nullable=True)   # H3 index at res 9 (~1 km)
    geocell_ttl       = Column(DateTime(timezone=True), nullable=True)  # when geocell expires
    # Eligibility fields per Art 4 TT 26/2013
    birth_year        = Column(Integer, nullable=True)
    weight_kg        = Column(Integer, nullable=True)
    sex               = Column(String, nullable=True)     # M/F
    # Địa chỉ đẩy thông báo của thiết bị. Rỗng nghĩa là người hiến chỉ nhận được
    # lời kêu gọi khi mở app (kênh "store": app tự hỏi hộp thư).
    push_token        = Column(String, nullable=True)
    push_platform     = Column(String, nullable=True)     # android | ios
    push_updated_at   = Column(DateTime(timezone=True), nullable=True)

    # Bí mật thiết bị — băm PBKDF2, cấp MỘT lần lúc đăng ký lần đầu.
    #
    # Người hiến không có mật khẩu, nên nếu `/donors/register` cứ ai gửi `id` lên
    # là cấp token cho mã đó thì bất kỳ ai đoán được mã (mã seed là donor-0001,
    # donor-0002…) cũng chiếm được hồ sơ. Cột này là bằng chứng "tôi là thiết bị
    # đã đăng ký hồ sơ này" khi token cũ đã hết hạn.
    device_secret_hash = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_donor_abo_rh", abo, rh),
        Index("ix_donor_geocell", geocell_h3),
    )


class SOSEvent(Base):
    """Sự kiện huy động người hiến — leo thang 4 vòng."""
    __tablename__ = "sos_event"

    id            = Column(String, primary_key=True)
    request_id    = Column(String, ForeignKey("transfer_request.id"), nullable=True)
    ring          = Column(Integer, nullable=False)           # 0..3
    opened_at     = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    target_count  = Column(Integer, nullable=False)          # how many donors needed
    accept_count  = Column(Integer, default=0, nullable=False)

    # Bối cảnh lâm sàng của lời kêu gọi — thiếu mấy cột này thì server
    # không biết phải gọi nhóm máu nào, app BB-SOS gửi lên là 422.
    facility_id    = Column(String, ForeignKey("facility.id"), nullable=True)
    component_code = Column(String, nullable=True)   # WB | RBC | PLT | FFP | CRYO
    abo            = Column(String, nullable=True)   # nhóm máu người bệnh cần
    rh             = Column(String, nullable=True)
    recipient_sex  = Column(String(1), nullable=True)
    recipient_age  = Column(Integer, nullable=True)
    urgency        = Column(String, nullable=True)   # routine | urgent | emergency
    h3_cell        = Column(String, nullable=True)   # ô lưới H3 của cơ sở phát yêu cầu
    status         = Column(String, nullable=False, default="open")  # open|fulfilled|expired|cancelled|completed

    responses = relationship("SOSResponse", back_populates="event")


class SOSResponse(Base):
    """Phản hồi của người hiến đối với sự kiện SOS."""
    __tablename__ = "sos_response"

    id            = Column(String, primary_key=True)
    sos_event_id  = Column(String, ForeignKey("sos_event.id"), nullable=False)
    donor_id      = Column(String, ForeignKey("donor.id"), nullable=False)
    responded_at  = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    outcome       = Column(String, nullable=True)  # accepted|declined|no_show

    # Danh tính chỉ xuất hiện KHI người hiến nhận lời, và do chính họ tự nhập ở
    # bước đó. Máy chủ không có sẵn số điện thoại của ai để mà lộ.
    contact_phone = Column(String, nullable=True)
    contact_note  = Column(String, nullable=True)   # "sau 18h", "đang trên đường"...
    location_cell = Column(String, nullable=True)   # coarse H3, only after explicit consent
    location_latitude = Column(Float, nullable=True)
    location_longitude = Column(Float, nullable=True)
    location_sharing_consented = Column(Boolean, nullable=True)
    location_shared_at = Column(DateTime(timezone=True), nullable=True)

    # Vế đối của SOSEvent.responses. Thiếu quan hệ này thì SQLAlchemy không cấu
    # hình được mapper và MỌI truy vấn ORM đều hỏng ngay lần gọi đầu tiên.
    event = relationship("SOSEvent", back_populates="responses")

    __table_args__ = (
        # Một người hiến chỉ có MỘT phản hồi cho mỗi sự kiện. Không có ràng buộc
        # này thì hai lần gửi song song (app gửi lại sau timeout) lọt qua được
        # phép kiểm trong mã và số người nhận lời bị đếm gấp đôi.
        Index("ix_sos_response_event_donor", sos_event_id, donor_id, unique=True),
    )


class SOSNotification(Base):
    """
    Một lời kêu gọi đã gửi tới một người hiến, ở một vòng cụ thể.

    Bảng này là bằng chứng ghi vết: ai được gọi, vòng mấy, lúc nào, qua kênh gì.
    Nó cũng là HỘP THƯ để app hỏi khi không có kênh đẩy — không có nó thì lời kêu
    gọi chỉ tồn tại trong log máy chủ và không bao giờ tới được điện thoại.
    """
    __tablename__ = "sos_notification"

    id            = Column(String, primary_key=True)
    sos_event_id  = Column(String, ForeignKey("sos_event.id"), nullable=False)
    donor_id      = Column(String, ForeignKey("donor.id"), nullable=False)
    ring          = Column(Integer, nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    channel       = Column(String, nullable=False)         # fcm | store
    status        = Column(String, nullable=False, default="pending")  # pending|sent|failed|read
    error         = Column(String, nullable=True)
    delivered_at  = Column(DateTime(timezone=True), nullable=True)
    read_at       = Column(DateTime(timezone=True), nullable=True)

    event = relationship("SOSEvent")

    __table_args__ = (
        # Một người hiến chỉ nhận MỘT lần cho mỗi sự kiện, dù leo thang qua nhiều
        # vòng — nếu không, người ở vòng 0 sẽ bị gọi lại ở vòng 1, 2 và 3.
        Index("ix_sos_notif_event_donor", sos_event_id, donor_id, unique=True),
        Index("ix_sos_notif_donor_status", donor_id, status),
    )


class SOSReward(Base):
    """Proposed, mock-only donor incentives attached to an SOS event."""
    __tablename__ = "sos_reward"

    id                     = Column(String, primary_key=True)
    sos_event_id           = Column(String, ForeignKey("sos_event.id"), nullable=False)
    donor_id               = Column(String, ForeignKey("donor.id"), nullable=False)
    role                   = Column(String, nullable=False)  # primary | backup
    status                 = Column(String, nullable=False)  # awaiting_donation | awaiting_choice | compensation_proposed | mock_ready | not_completed
    proposed_amount_vnd    = Column(Integer, nullable=True)
    created_at             = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    decision_at            = Column(DateTime(timezone=True), nullable=True)
    donation_confirmed_at  = Column(DateTime(timezone=True), nullable=True)
    donation_confirmed_by  = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_sos_reward_event_donor", sos_event_id, donor_id, unique=True),
    )


class AppUser(Base):
    """
    Tài khoản đăng nhập BB-Console.

    Người hiến KHÔNG có dòng ở đây: họ định danh bằng mã người hiến do app sinh,
    và nhận token ngay lúc đăng ký hồ sơ. Bảng này chỉ dành cho nhân viên cơ sở
    y tế và quản trị.
    """
    __tablename__ = "app_user"

    id            = Column(String, primary_key=True)
    username      = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role          = Column(String, nullable=False)      # facility_staff | admin
    facility_id   = Column(String, ForeignKey("facility.id"), nullable=True)
    full_name     = Column(String, nullable=True)
    active        = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index("ix_app_user_username", username, unique=True),
    )


class AuditLog(Base):
    """Nhật ký ghi vết chuỗi băm, chỉ thêm (append-only)."""
    __tablename__ = "audit_log"

    id          = Column(String, primary_key=True)
    prev_hash   = Column(String, nullable=True)    # hash of previous row
    hash        = Column(String, nullable=False)     # SHA-256(this row)
    actor       = Column(String, nullable=False)
    action      = Column(String, nullable=False)
    # JSON có biến thể JSONB: Postgres vẫn dùng jsonb, còn SQLite (dùng trong
    # test) hiểu được JSON thường — nhờ vậy nhật ký kiểm được mà không cần Postgres.
    payload_json = Column(JSON().with_variant(JSONB, "postgresql"), default={}, nullable=False)
    at          = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    @staticmethod
    def compute_hash(prev_hash: str, actor: str, action: str, payload: dict, at: datetime) -> str:
        """Deterministic hash for audit chain integrity."""
        data = f"{prev_hash}|{actor}|{action}|{sorted(payload.items())}|{at.isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()
