"""
BB-Core — Donor API: đăng ký người hiến và cập nhật ô lưới H3.

Đây là mảnh còn thiếu khiến app BB-SOS chỉ là form điền thông tin: bảng `donor`
trước đây chỉ có dữ liệu seed, không có đường nào để hồ sơ thật đi vào hệ thống,
nên `/api/sos/donors/nearby` luôn trả về 0 người với người dùng thật.

Ràng buộc giữ nguyên theo thiết kế:
  - KHÔNG nhận toạ độ thô. Chỉ nhận chỉ số ô lưới H3 (~1.2 km, res 7) kèm TTL.
  - KHÔNG lưu họ tên / số điện thoại. Hồ sơ định danh nằm cục bộ trên máy người dùng.
  - `verified` do cơ sở y tế đặt, người hiến không tự xác minh được.
"""

import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.database import Donor, Facility, SOSEvent, SOSNotification, ABO, RhD
from app.services import audit
from app.services.eligibility import donation_eligibility, eligible_cutoff
from app.services.sos_dispatch import build_message
from app.services.auth import create_access_token, hash_password, verify_password, ROLE_DONOR
from app.api.deps import (
    Principal,
    get_principal,
    get_principal_optional,
    require_staff,
    require_self_or_staff,
)
from app.api.schemas import (
    DonorRegisterIn,
    DonorGeocellIn,
    DonorDonationIn,
    DonorVerifyIn,
    DonorOut,
    DonorRegisterOut,
    DonorPushTokenIn,
    SOSInboxItem,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────

def parse_abo(value: str) -> ABO:
    try:
        return ABO(value.strip().upper())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Nhóm máu ABO không hợp lệ: {value} (O/A/B/AB)")


def parse_rh(value: str) -> RhD:
    v = value.strip()
    aliases = {"+": "+", "-": "-", "POS": "+", "NEG": "-", "POSITIVE": "+", "NEGATIVE": "-"}
    v = aliases.get(v.upper(), v)
    try:
        return RhD(v)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"RhD không hợp lệ: {value} (+ hoặc -)")


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def donor_out(d: Donor, component: Optional[str] = None) -> DonorOut:
    """Chuyển ORM → schema, kèm kết quả tính điều kiện hiến (Điều 6)."""
    now = datetime.now(timezone.utc)
    elig = donation_eligibility(d.last_donation_at, component=component, now=now)
    ttl = as_utc(d.geocell_ttl)

    return DonorOut(
        id=d.id,
        abo=d.abo.value,
        rh=d.rh.value,
        blood_type=f"{d.abo.value}{d.rh.value}",
        verified=d.verified,
        birth_year=d.birth_year,
        sex=d.sex,
        weight_kg=d.weight_kg,
        last_donation_at=d.last_donation_at,
        geocell_h3=d.geocell_h3,
        geocell_ttl=d.geocell_ttl,
        geocell_valid=bool(d.geocell_h3 and ttl and ttl > now),
        **elig,
    )


async def get_or_404(db: AsyncSession, donor_id: str) -> Donor:
    donor = await db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy người hiến {donor_id}")
    return donor


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/register", response_model=DonorRegisterOut)
async def register_donor(
    req: DonorRegisterIn,
    db: AsyncSession = Depends(get_db),
    principal: Optional[Principal] = Depends(get_principal_optional),
):
    """
    Đăng ký hồ sơ người hiến, hoặc cập nhật hồ sơ mình đã đăng ký.

    Endpoint DUY NHẤT trong nhóm này gọi được khi chưa có token — đây là bước
    đăng ký. Nhưng nó CẤP token, nên không thể để ai gửi `id` gì cũng nhận được
    token của mã đó: mã người hiến không phải bí mật (mã seed là `donor-0001`…,
    còn mã thật thì mọi tài khoản nhân viên đều đọc được qua
    `/sos/donors/nearby`).

    Vì vậy khi `id` trỏ tới hồ sơ ĐÃ TỒN TẠI, người gọi phải chứng minh là chủ
    hồ sơ bằng một trong hai cách:

      1. gửi kèm token còn hạn của chính người hiến đó (hoặc token nhân viên), hoặc
      2. gửi `device_secret` đã nhận ở lần đăng ký đầu tiên.

    Không có cái nào thì trả 403 — chứ KHÔNG âm thầm ghi đè nhóm máu của người
    khác rồi cấp token cho kẻ gọi.

    Gọi lại nhiều lần vẫn an toàn: app gọi mỗi lần người dùng bấm "Lưu hồ sơ",
    và đây cũng là đường "đăng nhập lại" khi token cũ hết hạn.
    """
    donor_id = req.id or str(uuid.uuid4())
    abo, rh = parse_abo(req.abo), parse_rh(req.rh)

    donor = await db.get(Donor, donor_id)
    new_secret: Optional[str] = None
    created = donor is None

    if donor is None:
        donor = Donor(id=donor_id, abo=abo, rh=rh, verified=False)
        new_secret = secrets.token_urlsafe(32)
        donor.device_secret_hash = hash_password(new_secret)
        db.add(donor)
    else:
        by_token = principal is not None and (
            principal.is_staff or (principal.is_donor and principal.subject == donor_id)
        )
        by_secret = bool(
            donor.device_secret_hash
            and req.device_secret
            and verify_password(req.device_secret, donor.device_secret_hash)
        )
        if not (by_token or by_secret):
            await audit.record(db, donor_id, audit.DONOR_REGISTER, {"result": "denied"})
            await db.commit()
            raise HTTPException(
                status_code=403,
                detail="Mã người hiến này đã được đăng ký. Cần token còn hạn hoặc "
                       "device_secret của lần đăng ký đầu để cập nhật.",
            )

        # Hồ sơ cũ (đăng ký trước khi có cơ chế này, hoặc dữ liệu seed) chưa có
        # bí mật nào. Người gọi vừa chứng minh được quyền bằng token, nên cấp
        # cho họ một bí mật để lần sau token hết hạn vẫn khôi phục được.
        if not donor.device_secret_hash:
            new_secret = secrets.token_urlsafe(32)
            donor.device_secret_hash = hash_password(new_secret)

        donor.abo, donor.rh = abo, rh

    if req.birth_year is not None:
        donor.birth_year = req.birth_year
    if req.sex is not None:
        donor.sex = req.sex.strip().upper()[:1]
    if req.weight_kg is not None:
        donor.weight_kg = req.weight_kg
    if req.last_donation_at is not None:
        donor.last_donation_at = req.last_donation_at

    if req.h3_cell:
        donor.geocell_h3 = req.h3_cell
        donor.geocell_ttl = datetime.now(timezone.utc) + timedelta(hours=req.geocell_ttl_hours)

    await audit.record(db, donor.id, audit.DONOR_REGISTER, {
        "created": created,
        "has_geocell": bool(req.h3_cell),
    })
    await db.commit()
    await db.refresh(donor)

    base = donor_out(donor)
    return DonorRegisterOut(
        **base.model_dump(),
        access_token=create_access_token(donor.id, ROLE_DONOR),
        expires_in=settings.jwt_expire_minutes * 60,
        device_secret=new_secret,
    )


@router.get("/{donor_id}", response_model=DonorOut)
async def get_donor(
    donor_id: str,
    component_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Đọc lại hồ sơ đã đăng ký — app dùng để đồng bộ trạng thái xác minh."""
    require_self_or_staff(principal, donor_id)
    donor = await get_or_404(db, donor_id)
    return donor_out(donor, component=component_code)


@router.patch("/{donor_id}/geocell", response_model=DonorOut)
async def update_geocell(
    donor_id: str,
    req: DonorGeocellIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """
    Làm mới ô lưới H3 + TTL. App gọi định kỳ khi người dùng còn bật chia sẻ vị trí;
    hết TTL thì `/sos/donors/nearby` tự động bỏ qua người này.
    """
    require_self_or_staff(principal, donor_id)
    donor = await get_or_404(db, donor_id)
    donor.geocell_h3 = req.h3_cell
    donor.geocell_ttl = datetime.now(timezone.utc) + timedelta(hours=req.ttl_hours)
    await db.commit()
    await db.refresh(donor)
    return donor_out(donor)


@router.delete("/{donor_id}/geocell", response_model=DonorOut)
async def revoke_geocell(
    donor_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Rút lại đồng ý chia sẻ vị trí — xoá ô lưới ngay, không đợi TTL."""
    require_self_or_staff(principal, donor_id)
    donor = await get_or_404(db, donor_id)
    donor.geocell_h3 = None
    donor.geocell_ttl = None
    await db.commit()
    await db.refresh(donor)
    return donor_out(donor)


@router.post("/{donor_id}/donation", response_model=DonorOut)
async def record_donation(
    donor_id: str,
    req: DonorDonationIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Ghi nhận một lần hiến — mốc để tính khoảng cách theo Điều 6."""
    require_self_or_staff(principal, donor_id)
    donor = await get_or_404(db, donor_id)
    donated_at = req.donated_at or datetime.now(timezone.utc)
    if as_utc(donated_at) > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Thời điểm hiến không thể ở tương lai")

    current = as_utc(donor.last_donation_at)
    if current is None or as_utc(donated_at) > current:
        donor.last_donation_at = donated_at

    await db.commit()
    await db.refresh(donor)
    return donor_out(donor, component=req.component_code)


@router.post("/{donor_id}/verify", response_model=DonorOut)
async def verify_donor(
    donor_id: str,
    req: DonorVerifyIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Cơ sở y tế xác minh người hiến. Chỉ người đã xác minh mới hiện trong
    tìm kiếm mặc định của BB-Console.

    Người hiến KHÔNG tự gọi được — vai trò `donor` bị chặn ở đây.
    """
    donor = await get_or_404(db, donor_id)
    donor.verified = req.verified
    await audit.record(db, principal.subject, audit.DONOR_VERIFY, {
        "donor_id": donor_id, "verified": req.verified,
        "verified_by": req.verified_by or principal.facility_id,
    })
    await db.commit()
    await db.refresh(donor)
    return donor_out(donor)


@router.put("/{donor_id}/push-token", response_model=DonorOut)
async def set_push_token(
    donor_id: str,
    req: DonorPushTokenIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """
    Đăng ký (hoặc gỡ) địa chỉ nhận thông báo đẩy của thiết bị.

    Chưa có token thì người hiến vẫn nhận được lời kêu gọi — app hỏi hộp thư ở
    `/donors/{id}/sos-inbox`, chỉ là phải mở app mới thấy.
    """
    require_self_or_staff(principal, donor_id)
    donor = await get_or_404(db, donor_id)

    donor.push_token = (req.push_token or "").strip() or None
    donor.push_platform = req.platform if donor.push_token else None
    donor.push_updated_at = datetime.now(timezone.utc) if donor.push_token else None

    await db.commit()
    await db.refresh(donor)
    return donor_out(donor)


@router.get("/{donor_id}/sos-inbox", response_model=list[SOSInboxItem])
async def sos_inbox(
    donor_id: str,
    include_read: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """
    Những lời kêu gọi đang chờ người hiến này trả lời.

    Đây là kênh giao hàng thật sự khi chưa có Firebase: app hỏi hộp thư rồi tự
    dựng thông báo trên máy. Chỉ trả lời kêu gọi CÒN MỞ — sự kiện đã đủ người
    hoặc quá hạn thì không réo nữa.
    """
    require_self_or_staff(principal, donor_id)

    stmt = (
        select(SOSNotification, SOSEvent)
        .join(SOSEvent, SOSEvent.id == SOSNotification.sos_event_id)
        .where(SOSNotification.donor_id == donor_id)
        .where(SOSEvent.status == "open")
        .order_by(SOSNotification.created_at.desc())
        .limit(limit)
    )
    if not include_read:
        stmt = stmt.where(SOSNotification.status != "read")

    rows = (await db.execute(stmt)).all()

    items = []
    for notification, event in rows:
        facility = await db.get(Facility, event.facility_id) if event.facility_id else None
        title, body = build_message(event, facility.name if facility else None)
        blood = f"{event.abo or ''}{event.rh or ''}".strip() or None

        items.append(SOSInboxItem(
            notification_id=notification.id,
            event_id=event.id,
            ring=notification.ring,
            notified_at=notification.created_at,
            status=notification.status,
            abo=event.abo,
            rh=event.rh,
            blood_type=blood,
            component_code=event.component_code,
            urgency=event.urgency,
            target_count=event.target_count,
            accept_count=event.accept_count or 0,
            event_status=event.status or "open",
            opened_at=event.opened_at,
            facility_id=event.facility_id,
            facility_name=facility.name if facility else None,
            title=title,
            body=body,
        ))
    return items


@router.get("", response_model=list[DonorOut])
async def list_donors(
    abo: Optional[str] = None,
    rh: Optional[str] = None,
    verified_only: bool = False,
    with_geocell: bool = False,
    component_code: Optional[str] = None,
    eligible_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Danh sách người hiến cho BB-Console — tra theo nhóm máu, không cần vị trí.

    Đây là truy vấn "tìm người cùng nhóm máu" ở mức toàn thành phố; muốn giới hạn
    theo bán kính thì dùng `/api/sos/donors/nearby`.
    """
    stmt = select(Donor)
    if abo:
        stmt = stmt.where(Donor.abo == parse_abo(abo))
    if rh:
        stmt = stmt.where(Donor.rh == parse_rh(rh))
    if verified_only:
        stmt = stmt.where(Donor.verified.is_(True))
    if with_geocell:
        stmt = stmt.where(Donor.geocell_h3.is_not(None))
        stmt = stmt.where(Donor.geocell_ttl > datetime.now(timezone.utc))

    if eligible_only:
        # Cùng lý do như /sos/donors/nearby: lọc sau LIMIT thì phân trang sai.
        cutoff = eligible_cutoff(component_code)
        stmt = stmt.where(
            (Donor.last_donation_at.is_(None)) | (Donor.last_donation_at <= cutoff)
        )

    stmt = stmt.order_by(Donor.id).limit(limit).offset(offset)
    donors = (await db.execute(stmt)).scalars().all()

    await audit.record(db, principal.subject, audit.DONOR_LIST, {
        "abo": abo, "rh": rh, "verified_only": verified_only,
        "eligible_only": eligible_only, "results": len(donors),
    })
    await db.commit()

    return [donor_out(d, component=component_code) for d in donors]
