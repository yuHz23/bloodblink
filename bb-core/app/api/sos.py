"""
BB-Core — SOS API: huy động người hiến theo 4 vòng + ô lưới H3.

Việc chọn người và gửi lời kêu gọi nằm ở `services/sos_dispatch.py` vì bộ lập
lịch (`services/scheduler.py`) cũng dùng chung — endpoint ở đây chỉ lo phân
quyền, kiểm tra đầu vào và định dạng đáp.

  - `/event` nhận đúng payload app BB-SOS gửi (facility_id, component_code,
    abo, rh, urgency, qty) và trả về {id, status, message} như app đang đọc.
  - `/event/{id}/escalate` nâng vòng trên CHÍNH sự kiện đó, chỉ gọi người mới.
  - `/event/{id}/respond` nhận JSON body thay vì query param.
  - `/donors/nearby` trả cả tên trường app đọc (`total_donors`, `eligible`)
    lẫn tên trường BB-Console đang dùng.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import h3
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import Donor, SOSEvent, SOSResponse, SOSNotification, ABO, RhD
from app.services import audit
from app.services.eligibility import donation_eligibility, eligible_cutoff
from app.services.sos_dispatch import (
    RING_LABEL, apply_geocell_filter, cells_for_ring, facility_cell,
    dispatch_ring, escalate_event,
)
from app.api.deps import Principal, get_principal, require_staff, require_self_or_staff
from app.api.schemas import (
    SOSEventIn, SOSEventOut, SOSRespondIn, SOSNotificationOut, SOSResponderOut,
)

router = APIRouter()


def _describe(event: SOSEvent, matched: int, notified: int, cell: Optional[str]) -> str:
    blood = f"{event.abo}{event.rh}" if event.abo and event.rh else "mọi nhóm"
    label = RING_LABEL[max(0, min(event.ring, 3))]

    if matched:
        extra = f", gọi thêm {notified} người" if notified != matched else ""
        return (f"{label}: tìm được {matched} người hiến {blood} đủ điều kiện cho "
                f"{event.component_code}, cần {event.target_count}{extra}.")
    if cell is None and event.ring < 3:
        return "Chưa xác định được ô lưới của cơ sở — gửi kèm h3_cell hoặc facility_id hợp lệ."
    return (f"{label}: chưa có người hiến {blood} nào đủ điều kiện. "
            f"Hãy nâng lên vòng {min(event.ring + 1, 3)}.")


def _event_out(event: SOSEvent, *, message: str = "", notified: int = 0) -> SOSEventOut:
    out = SOSEventOut.model_validate(event)
    out.status = event.status or "open"
    out.message = message
    out.donors_notified = notified
    return out


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/event", response_model=SOSEventOut)
async def create_sos_event(
    req: SOSEventIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Mở một lời kêu gọi hiến máu và gửi ngay cho người hiến của vòng hiện tại.

    Từ P2, bộ lập lịch tự nâng vòng theo mốc T+0/10/25/45 phút; muốn nâng sớm thì
    gọi `/event/{id}/escalate`.
    """
    cell = req.h3_cell or await facility_cell(db, req.facility_id)

    event = SOSEvent(
        id=str(uuid.uuid4()),
        request_id=req.request_id,
        ring=req.ring,
        opened_at=datetime.now(timezone.utc),
        target_count=req.target_count or req.qty,
        accept_count=0,
        facility_id=req.facility_id,
        component_code=(req.component_code or "WB").upper(),
        abo=req.abo,
        rh=req.rh,
        urgency=req.urgency,
        h3_cell=cell,
        status="open",
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    result = await dispatch_ring(db, event)

    await audit.record(db, principal.subject, audit.SOS_OPEN, {
        "event_id": event.id, "facility_id": event.facility_id,
        "abo": event.abo, "rh": event.rh, "component": event.component_code,
        "ring": event.ring, "target": event.target_count,
        "donors_notified": result.notified,
    })
    await db.commit()

    return _event_out(event,
                      message=_describe(event, result.matched, result.notified, cell),
                      notified=result.notified)


@router.post("/event/{event_id}/escalate", response_model=SOSEventOut)
async def escalate_sos_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Nâng lời kêu gọi lên vòng kế tiếp NGAY, không đợi mốc thời gian.

    Leo thang trên chính sự kiện đó và chỉ gọi những người vòng trước chưa với
    tới — không tạo sự kiện mới, không réo lại người đã được gọi.
    """
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    if event.status != "open":
        raise HTTPException(status_code=409,
                            detail=f"Sự kiện đang ở trạng thái '{event.status}', không leo thang được")
    if event.ring >= 3:
        raise HTTPException(status_code=409, detail="Đã ở vòng 3 — không còn vòng nào rộng hơn")

    result = await escalate_event(db, event)

    await audit.record(db, principal.subject, audit.SOS_ESCALATE, {
        "event_id": event.id, "ring": event.ring,
        "donors_notified": result.notified,
        "already_notified": result.already_notified,
    })
    await db.commit()

    return _event_out(event,
                      message=_describe(event, result.matched, result.notified, event.h3_cell),
                      notified=result.notified)


@router.get("/event/{event_id}", response_model=SOSEventOut)
async def get_sos_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """
    Trạng thái một lời kêu gọi — app và console đều dùng để cập nhật màn hình.

    Nhân viên đọc được mọi sự kiện. Người hiến CHỈ đọc được sự kiện mà chính họ
    được gọi: trước đây endpoint này chỉ đòi có token, nên một tài khoản người
    hiến bất kỳ dò mã sự kiện là đọc được cơ sở, nhóm máu, mức khẩn và số người
    đã nhận lời của ca không liên quan tới mình.

    Không chặn cứng theo vai trò được — app phải đọc chính endpoint này cho ca nó
    được mời — nên điều kiện là "nhân viên HOẶC có lời kêu gọi gửi cho mình".
    """
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")

    if not principal.is_staff:
        invited = (await db.execute(
            select(SOSNotification.id).where(
                SOSNotification.sos_event_id == event_id,
                SOSNotification.donor_id == principal.subject,
            ).limit(1)
        )).scalar_one_or_none()
        if invited is None:
            # 404 chứ không phải 403: trả 403 là xác nhận "mã sự kiện này có
            # thật", đủ để dò xem cơ sở nào đang có ca cấp cứu.
            raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")

    notified = len((await db.execute(
        select(SOSNotification.id).where(SOSNotification.sos_event_id == event_id)
    )).scalars().all())

    return _event_out(
        event,
        message=f"Đã nhận {event.accept_count}/{event.target_count} người hiến",
        notified=notified,
    )


@router.get("/event/{event_id}/notifications", response_model=list[SOSNotificationOut])
async def list_event_notifications(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Ai đã được gọi, ở vòng nào, qua kênh gì — nhật ký ghi vết của lời kêu gọi."""
    if not await db.get(SOSEvent, event_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")

    rows = (await db.execute(
        select(SOSNotification)
        .where(SOSNotification.sos_event_id == event_id)
        .order_by(SOSNotification.ring, SOSNotification.created_at)
    )).scalars().all()
    return [SOSNotificationOut.model_validate(r) for r in rows]


@router.get("/event/{event_id}/responses", response_model=list[SOSResponderOut])
async def list_responders(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Người hiến đã NHẬN LỜI, kèm cách liên hệ họ tự cung cấp.

    Đây là điểm duy nhất trong hệ thống lộ ra thứ liên hệ được với một con người
    cụ thể, nên có ba ràng buộc:
      1. Chỉ cơ sở phát lời kêu gọi (hoặc quản trị) đọc được — cơ sở khác không.
      2. Chỉ người đã nhận lời mới có mặt; người từ chối không lưu liên hệ.
      3. Mỗi lần đọc để lại một dòng trong nhật ký ghi vết.
    """
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")

    if principal.role != "admin" and event.facility_id and principal.facility_id != event.facility_id:
        raise HTTPException(
            status_code=403,
            detail="Chỉ cơ sở phát lời kêu gọi mới xem được danh sách người nhận lời",
        )

    rows = (await db.execute(
        select(SOSResponse)
        .where(SOSResponse.sos_event_id == event_id)
        .where(SOSResponse.outcome == "accepted")
        .order_by(SOSResponse.responded_at)
    )).scalars().all()

    out = []
    for r in rows:
        donor = await db.get(Donor, r.donor_id)
        out.append(SOSResponderOut(
            donor_id=r.donor_id,
            blood_type=f"{donor.abo.value}{donor.rh.value}" if donor else None,
            outcome=r.outcome or "accepted",
            responded_at=r.responded_at,
            contact_phone=r.contact_phone,
            contact_note=r.contact_note,
        ))

    await audit.record(db, principal.subject, audit.CONTACT_REVEAL, {
        "event_id": event_id, "revealed": len(out),
        "with_phone": sum(1 for r in out if r.contact_phone),
    })
    await db.commit()
    return out


@router.get("/donors/nearby")
async def find_nearby_donors(
    h3_cell: str,
    abo: Optional[str] = None,
    rh: Optional[str] = None,
    component_code: str = "WB",
    ring: int = 0,
    verified_only: bool = True,
    eligible_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Tìm người hiến quanh một ô lưới H3. Bán kính nở theo `ring`, không dùng toạ
    độ thô. Không trả về vị trí, chỉ trả mã người hiến và nhóm máu.
    """
    # Vòng 3 là cảnh báo toàn thành phố nên KHÔNG lọc theo ô lưới — giống hệt
    # cách /sos/event xử lý. Trước đây chỗ này rơi về đúng một ô, khiến vòng 3
    # hành xử y như vòng 0.
    cells = cells_for_ring(h3_cell, ring)
    now = datetime.now(timezone.utc)

    # Dùng CHUNG vị ngữ với `select_donors` — xem `apply_geocell_filter`. Viết lại
    # điều kiện ở đây là cách con số trên console lệch với số người thật sự được gọi.
    stmt = apply_geocell_filter(select(Donor), cells, now)

    if abo:
        try:
            stmt = stmt.where(Donor.abo == ABO(abo.upper()))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Nhóm máu ABO không hợp lệ: {abo}")
    if rh:
        try:
            stmt = stmt.where(Donor.rh == RhD(rh))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"RhD không hợp lệ: {rh}")
    if verified_only:
        stmt = stmt.where(Donor.verified.is_(True))

    component = (component_code or "WB").upper()
    if eligible_only:
        # Lọc điều kiện hiến NGAY TRONG SQL, trước LIMIT — xem `eligible_cutoff`.
        cutoff = eligible_cutoff(component, now)
        stmt = stmt.where(
            (Donor.last_donation_at.is_(None)) | (Donor.last_donation_at <= cutoff)
        )

    stmt = stmt.limit(limit)
    donors = (await db.execute(stmt)).scalars().all()

    rows = []
    for d in donors:
        elig = donation_eligibility(d.last_donation_at, component=component, now=now)
        rows.append({
            "donor_id": d.id,
            "abo": d.abo.value,
            "rh": d.rh.value,
            "blood_type": f"{d.abo.value}{d.rh.value}",
            "h3_cell": d.geocell_h3,
            "verified": d.verified,
            "reachable_by_push": bool(d.push_token),
            **elig,
        })

    await audit.record(db, principal.subject, audit.DONOR_SEARCH, {
        "h3_cell": h3_cell, "ring": ring, "component": component,
        "abo": abo, "rh": rh, "results": len(rows),
    })
    await db.commit()

    return {
        "h3_cell": h3_cell,
        "ring": ring,
        "component_code": component,
        "cells_searched": cells,          # None = vòng 3, không giới hạn vị trí
        "citywide": cells is None,
        # `donors_found` cho BB-Console, `total_donors` cho app BB-SOS
        "donors_found": len(rows),
        "total_donors": len(rows),
        "donors": rows,
    }


@router.get("/events", response_model=list[SOSEventOut])
async def list_sos_events(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Các lời kêu gọi, mới nhất trước — bản đồ dùng để chấm "chỗ nào đang cần".

    Trước đây chỉ đọc được MỘT sự kiện nếu đã biết mã của nó, nên không màn nào
    trả lời được câu "toàn thành phố đang có bao nhiêu ca cần máu".
    """
    stmt = select(SOSEvent).order_by(desc(SOSEvent.opened_at)).limit(limit)
    if status:
        stmt = stmt.where(SOSEvent.status == status)

    events = (await db.execute(stmt)).scalars().all()

    out = []
    for event in events:
        notified = len((await db.execute(
            select(SOSNotification.id).where(SOSNotification.sos_event_id == event.id)
        )).scalars().all())
        out.append(_event_out(event, notified=notified))
    return out


@router.get("/donors/density")
async def donor_density(
    abo: Optional[str] = None,
    rh: Optional[str] = None,
    min_donors: int = Query(default=3, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """
    Mật độ người hiến theo ô lưới H3 — dữ liệu để tô bản đồ nhiệt.

    KHÔNG trả mã người hiến. Bản đồ chỉ được biết "ô này có bao nhiêu người",
    không bao giờ biết "ai đang ở đâu" — hệ thống cố tình chỉ lưu ô lưới ~1,2 km
    chứ không lưu toạ độ, và chấm từng người lên bản đồ sẽ phá đúng cam kết đó.

    `min_donors` là ngưỡng k-ẩn danh: ô có ít hơn ngần ấy người thì BỎ HẲN,
    không trả về. Một ô lưới chỉ có đúng một người, đặt cạnh một tấm ảnh hay một
    lời kể, là đủ để lần ra người đó. Ở môi trường thật đừng hạ xuống dưới 3.
    """
    now = datetime.now(timezone.utc)

    stmt = (
        select(Donor.geocell_h3, func.count(Donor.id).label("count"))
        .where(
            Donor.geocell_h3.is_not(None),
            Donor.geocell_ttl > now,
            Donor.verified.is_(True),
        )
        .group_by(Donor.geocell_h3)
    )
    if abo:
        try:
            stmt = stmt.where(Donor.abo == ABO(abo.upper()))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Nhóm máu ABO không hợp lệ: {abo}")
    if rh:
        try:
            stmt = stmt.where(Donor.rh == RhD(rh))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"RhD không hợp lệ: {rh}")

    rows = (await db.execute(stmt)).all()

    cells = []
    suppressed = 0
    for r in rows:
        if r.count < min_donors:
            suppressed += 1
            continue
        lat, lon = h3.cell_to_latlng(r.geocell_h3)
        cells.append({
            "h3_cell": r.geocell_h3,
            "lat": lat,
            "lon": lon,
            "count": r.count,
            # Ranh giới ô để vẽ đa giác thay vì chấm tròn — nhìn ra ngay đây là
            # một VÙNG chứ không phải một người.
            "boundary": [[la, lo] for la, lo in h3.cell_to_boundary(r.geocell_h3)],
        })

    await audit.record(db, principal.subject, audit.DONOR_SEARCH, {
        "mode": "density", "abo": abo, "rh": rh,
        "cells": len(cells), "suppressed": suppressed,
    })
    await db.commit()

    return {
        "cells": cells,
        "min_donors": min_donors,
        "suppressed_cells": suppressed,
        "resolution": settings.h3_resolution,
    }


@router.post("/event/{event_id}/respond")
async def donor_respond(
    event_id: str,
    req: SOSRespondIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Ghi nhận phản hồi của người hiến — app gửi JSON body {donor_id, response}."""
    # Người hiến không trả lời thay người khác được.
    require_self_or_staff(principal, req.donor_id)

    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")

    outcome = req.resolved_outcome
    if outcome not in ("accepted", "declined", "no_show"):
        raise HTTPException(
            status_code=422,
            detail="outcome phải là accepted | declined | no_show",
        )

    now = datetime.now(timezone.utc)
    accepted = outcome == "accepted"

    # Lời kêu gọi đã gửi tới người này chưa? Nó vừa là cái để đánh dấu "đã đọc",
    # vừa là điều kiện được trả lời: không ai được nhận lời cho một ca mà mình
    # chưa hề được gọi (mã sự kiện là UUID nhưng vẫn đi qua tay app).
    notification = (await db.execute(
        select(SOSNotification).where(
            SOSNotification.sos_event_id == event_id,
            SOSNotification.donor_id == req.donor_id,
        )
    )).scalar_one_or_none()
    if notification is None and not principal.is_staff:
        raise HTTPException(
            status_code=403,
            detail="Người hiến này không nằm trong danh sách được gọi của sự kiện",
        )

    # Trả lời LẠI thì sửa chính dòng cũ, không thêm dòng mới.
    #
    # Đây là chỗ hỏng nặng nhất trước đây: app timeout SAU khi máy chủ đã commit,
    # người hiến bấm "Nhận lời" lần nữa → `accept_count` cộng 2 cho MỘT người →
    # ca cần 2 người bị đánh dấu đủ → bộ lập lịch (chỉ quét status "open") thôi
    # nâng vòng và không ai được gọi thêm nữa.
    response = (await db.execute(
        select(SOSResponse).where(
            SOSResponse.sos_event_id == event_id,
            SOSResponse.donor_id == req.donor_id,
        )
    )).scalars().first()

    if response is None:
        response = SOSResponse(
            id=str(uuid.uuid4()),
            sos_event_id=event_id,
            donor_id=req.donor_id,
        )
        db.add(response)

    response.responded_at = now
    response.outcome = outcome
    # Chỉ giữ liên hệ khi người hiến NHẬN LỜI. Từ chối mà vẫn lưu số điện
    # thoại là thu thập dữ liệu không có mục đích — và đổi ý sang "từ chối"
    # thì phải XOÁ số đã lưu, không để lại.
    response.contact_phone = (req.contact_phone or None) if accepted else None
    response.contact_note = (req.contact_note or None) if accepted else None

    # Trả lời rồi thì lời kêu gọi coi như đã đọc — app sẽ không hiện lại nữa.
    if notification is not None:
        notification.status = "read"
        notification.read_at = now

    # Đếm lại từ bảng phản hồi thay vì cộng dồn: cộng dồn thì mọi lần gửi lại,
    # mọi lần đổi ý đều làm số đếm sai và không có đường sửa.
    await db.flush()
    event.accept_count = (await db.execute(
        select(func.count(func.distinct(SOSResponse.donor_id))).where(
            SOSResponse.sos_event_id == event_id,
            SOSResponse.outcome == "accepted",
        )
    )).scalar_one() or 0
    if event.accept_count >= (event.target_count or 1):
        # Đủ người rồi thì bộ lập lịch thôi nâng vòng (chỉ quét status "open").
        event.status = "fulfilled"
    elif event.status == "fulfilled":
        # Có người rút lời → chưa đủ nữa → mở lại để leo thang tiếp.
        event.status = "open"

    await audit.record(db, req.donor_id, audit.SOS_RESPOND, {
        "event_id": event_id, "outcome": outcome, "ring": event.ring,
        "shared_contact": bool(accepted and req.contact_phone),
    })

    await db.commit()
    return {
        "status": "recorded",
        "event_id": event_id,
        "donor_id": req.donor_id,
        "outcome": outcome,
        "accept_count": event.accept_count,
        "target_count": event.target_count,
        "event_status": event.status,
    }
