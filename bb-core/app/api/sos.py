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
from datetime import datetime, timedelta, timezone
from typing import Optional

import h3
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import Donor, SOSEvent, SOSResponse, SOSNotification, SOSReward, TransferRequest, ABO, RhD
from app.services import audit
from app.services.eligibility import donation_eligibility, eligible_cutoff
from app.services.sos_dispatch import (
    RING_LABEL, apply_geocell_filter, cells_for_ring, facility_cell,
    dispatch_initial_rings, dispatch_ring, escalate_event,
)
from app.api.deps import Principal, get_principal, require_staff, require_self_or_staff
from app.api.schemas import (
    SOSEventIn, SOSEventOut, SOSRespondIn, SOSNotificationOut, SOSResponderOut,
    SOSResponderLocationOut, SOSRewardSelectIn, SOSRewardChoiceIn,
    SOSRewardDonationIn, SOSRewardOut,
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


def _require_event_facility(event: SOSEvent, principal: Principal) -> None:
    if principal.role != "admin" and (
        not event.facility_id or principal.facility_id != event.facility_id
    ):
        raise HTTPException(status_code=403, detail="Chỉ cơ sở phát SOS mới được truy cập dữ liệu của ca này")


async def _pending_reward_followup_count(db: AsyncSession, event_id: str) -> int:
    accepted_donors = set((await db.execute(
        select(SOSResponse.donor_id).where(
            SOSResponse.sos_event_id == event_id,
            SOSResponse.outcome == "accepted",
        )
    )).scalars())
    if not accepted_donors:
        return 0

    rewards = (await db.execute(
        select(SOSReward.donor_id, SOSReward.status).where(
            SOSReward.sos_event_id == event_id,
            SOSReward.donor_id.in_(accepted_donors),
        )
    )).all()
    reward_status_by_donor = {row.donor_id: row.status for row in rewards}
    terminal_statuses = {"compensation_proposed", "mock_ready", "not_completed"}
    return sum(
        reward_status_by_donor.get(donor_id) not in terminal_statuses
        for donor_id in accepted_donors
    )


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
    linked_facility_id = None
    if req.request_id:
        transfer_request = await db.scalar(
            select(TransferRequest)
            .where(TransferRequest.id == req.request_id)
            .with_for_update()
        )
        if transfer_request is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu điều chuyển liên kết")
        if principal.role != "admin" and principal.facility_id != transfer_request.requester_facility_id:
            raise HTTPException(status_code=403, detail="Chỉ cơ sở phát yêu cầu điều chuyển mới được mở SOS liên kết")
        if req.facility_id and req.facility_id != transfer_request.requester_facility_id:
            raise HTTPException(status_code=409, detail="Cơ sở phát SOS phải trùng với cơ sở yêu cầu điều chuyển")
        linked_facility_id = transfer_request.requester_facility_id
        existing = await db.scalar(
            select(SOSEvent).where(SOSEvent.request_id == req.request_id).limit(1)
        )
        if existing:
            notified = int(await db.scalar(
                select(func.count(SOSNotification.id)).where(SOSNotification.sos_event_id == existing.id)
            ) or 0)
            await db.commit()
            await db.refresh(existing)
            return _event_out(existing, message="SOS cho yêu cầu điều chuyển này đã được mở", notified=notified)

    facility_id = linked_facility_id or req.facility_id
    target_count = req.target_count or req.qty
    if not req.request_id:
        # A standalone SOS has no transfer request ID. Reuse an identical open
        # call so repeated clicks on the same form do not invite donors twice.
        existing = await db.scalar(
            select(SOSEvent)
            .where(
                SOSEvent.status == "open",
                SOSEvent.request_id.is_(None),
                SOSEvent.facility_id == facility_id,
                SOSEvent.component_code == (req.component_code or "WB").upper(),
                SOSEvent.abo == req.abo,
                SOSEvent.rh == req.rh,
                SOSEvent.urgency == req.urgency,
                SOSEvent.target_count == target_count,
            )
            .order_by(desc(SOSEvent.opened_at))
            .limit(1)
        )
        if existing:
            notified = int(await db.scalar(
                select(func.count(SOSNotification.id)).where(SOSNotification.sos_event_id == existing.id)
            ) or 0)
            return _event_out(existing, message="Đã có SOS cùng yêu cầu đang mở", notified=notified)

    cell = req.h3_cell or await facility_cell(db, facility_id)

    event = SOSEvent(
        id=str(uuid.uuid4()),
        request_id=req.request_id,
        ring=req.ring,
        opened_at=datetime.now(timezone.utc),
        target_count=target_count,
        accept_count=0,
        facility_id=facility_id,
        component_code=(req.component_code or "WB").upper(),
        abo=req.abo,
        rh=req.rh,
        urgency=req.urgency,
        h3_cell=cell,
        status="open",
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if req.request_id:
            existing = await db.scalar(
                select(SOSEvent).where(SOSEvent.request_id == req.request_id).limit(1)
            )
        else:
            existing = await db.scalar(
                select(SOSEvent).where(
                    SOSEvent.status == "open",
                    SOSEvent.request_id.is_(None),
                    SOSEvent.facility_id == facility_id,
                    SOSEvent.component_code == (req.component_code or "WB").upper(),
                    SOSEvent.abo == req.abo,
                    SOSEvent.rh == req.rh,
                    SOSEvent.urgency == req.urgency,
                    SOSEvent.target_count == target_count,
                ).limit(1)
            )
        if existing is None:
            raise
        notified = int(await db.scalar(
            select(func.count(SOSNotification.id)).where(SOSNotification.sos_event_id == existing.id)
        ) or 0)
        return _event_out(existing, message="SOS cho yêu cầu điều chuyển này đã được mở", notified=notified)

    await db.commit()
    await db.refresh(event)

    result, automatic_escalations = await dispatch_initial_rings(db, event)
    if result.notified == 0 and event.ring >= 3:
        event.status = "expired"
    if automatic_escalations:
        await audit.record(db, principal.subject, audit.SOS_ESCALATE, {
            "event_id": event.id,
            "ring": event.ring,
            "donors_notified": result.notified,
            "already_notified": result.already_notified,
            "automatic_escalations": automatic_escalations,
            "reason": "no_donors_found_in_previous_ring",
        })

    await audit.record(db, principal.subject, audit.SOS_OPEN, {
        "event_id": event.id, "facility_id": event.facility_id,
        "abo": event.abo, "rh": event.rh, "component": event.component_code,
        "ring": event.ring, "initial_ring": req.ring,
        "automatic_escalations": automatic_escalations,
        "target": event.target_count,
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


@router.post("/event/{event_id}/complete", response_model=SOSEventOut)
async def complete_sos_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Close a finished SOS while retaining its event and response history."""
    event = await db.scalar(
        select(SOSEvent).where(SOSEvent.id == event_id).with_for_update()
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    if principal.role != "admin" and (
        not event.facility_id or principal.facility_id != event.facility_id
    ):
        raise HTTPException(status_code=403, detail="Chỉ cơ sở phát SOS mới được hoàn tất ca này")
    if event.status == "completed":
        return _event_out(event, message="Ca SOS đã hoàn tất")
    if event.status == "cancelled":
        raise HTTPException(status_code=409, detail="Ca SOS đã bị hủy")
    if event.status not in ("fulfilled", "expired"):
        raise HTTPException(
            status_code=409,
            detail="Chỉ hoàn tất ca đã dừng tuyển người hiến",
        )

    pending_followups = await _pending_reward_followup_count(db, event_id)
    if pending_followups:
        raise HTTPException(
            status_code=409,
            detail=f"Còn {pending_followups} người nhận lời đang chờ xác nhận hiến hoặc phương án hỗ trợ",
        )

    previous_status = event.status
    event.status = "completed"
    responses = (await db.execute(
        select(SOSResponse).where(SOSResponse.sos_event_id == event_id)
    )).scalars().all()
    for response in responses:
        response.location_cell = None
        response.location_latitude = None
        response.location_longitude = None
        response.location_shared_at = None

    await audit.record(db, principal.subject, audit.SOS_COMPLETE, {
        "event_id": event.id,
        "previous_status": previous_status,
        "accept_count": event.accept_count,
        "target_count": event.target_count,
    })
    await db.commit()
    await db.refresh(event)
    return _event_out(event, message="Ca SOS đã hoàn tất")


@router.get("/event/{event_id}/notifications", response_model=list[SOSNotificationOut])
async def list_event_notifications(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Ai đã được gọi, ở vòng nào, qua kênh gì — nhật ký ghi vết của lời kêu gọi."""
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    _require_event_facility(event, principal)

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

    _require_event_facility(event, principal)

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
            location_sharing_consented=r.location_sharing_consented,
        ))

    await audit.record(db, principal.subject, audit.CONTACT_REVEAL, {
        "event_id": event_id, "revealed": len(out),
        "with_phone": sum(1 for r in out if r.contact_phone),
    })
    await db.commit()
    return out


@router.get("/event/{event_id}/locations", response_model=list[SOSResponderLocationOut])
async def list_shared_responder_locations(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Return exact GPS only to the hospital that opened this SOS, after consent."""
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    _require_event_facility(event, principal)
    if event.status not in ("open", "fulfilled"):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
    rows = (await db.execute(
        select(SOSResponse)
        .where(
            SOSResponse.sos_event_id == event_id,
            SOSResponse.outcome == "accepted",
            SOSResponse.location_sharing_consented.is_(True),
            SOSResponse.location_latitude.is_not(None),
            SOSResponse.location_longitude.is_not(None),
            SOSResponse.location_shared_at > cutoff,
        )
        .order_by(SOSResponse.location_shared_at)
    )).scalars().all()

    await audit.record(db, principal.subject, audit.SOS_LOCATION_REVEAL, {
        "event_id": event_id, "locations_revealed": len(rows),
    })
    await db.commit()
    return [SOSResponderLocationOut(
        latitude=row.location_latitude,
        longitude=row.location_longitude,
        shared_at=row.location_shared_at,
    ) for row in rows]


@router.get("/event/{event_id}/rewards", response_model=list[SOSRewardOut])
async def list_sos_rewards(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Phương án quà mô phỏng của nhóm người đã nhận lời trong một ca SOS."""
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    _require_event_facility(event, principal)
    rows = (await db.execute(
        select(SOSReward)
        .where(SOSReward.sos_event_id == event_id)
        .order_by(SOSReward.created_at, SOSReward.donor_id)
    )).scalars().all()
    return rows


@router.post("/event/{event_id}/rewards/select", response_model=list[SOSRewardOut])
async def select_sos_reward_recipients(
    event_id: str,
    req: SOSRewardSelectIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Chọn một người chính sau khi có ít nhất sáu người nhận lời; những người còn lại là dự bị."""
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    _require_event_facility(event, principal)
    if event.status == "cancelled":
        raise HTTPException(status_code=409, detail="Ca SOS đã bị hủy, không thể lập phương án quà")

    existing = (await db.execute(
        select(SOSReward.id).where(SOSReward.sos_event_id == event_id).limit(1)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Đã lập phương án quà cho SOS này")

    cohort = (await db.execute(
        select(SOSResponse)
        .where(SOSResponse.sos_event_id == event_id, SOSResponse.outcome == "accepted")
        .order_by(SOSResponse.responded_at, SOSResponse.id)
    )).scalars().all()
    if len(cohort) < 6:
        raise HTTPException(status_code=409, detail="Cần ít nhất 6 người nhận lời trước khi chọn")
    if req.primary_donor_id not in {r.donor_id for r in cohort}:
        raise HTTPException(status_code=422, detail="Chỉ chọn được người đã nhận lời SOS này")

    now = datetime.now(timezone.utc)
    for response in cohort:
        primary = response.donor_id == req.primary_donor_id
        db.add(SOSReward(
            id=str(uuid.uuid4()),
            sos_event_id=event_id,
            donor_id=response.donor_id,
            role="primary" if primary else "backup",
            status="awaiting_donation" if primary else "awaiting_choice",
            proposed_amount_vnd=100_000 if primary else None,
            created_at=now,
        ))

    await audit.record(db, principal.subject, audit.SOS_REWARD_SELECT, {
        "event_id": event_id, "primary_donor_id": req.primary_donor_id,
        "cohort_size": len(cohort), "mock_only": True,
    })
    await db.commit()
    rows = (await db.execute(
        select(SOSReward)
        .where(SOSReward.sos_event_id == event_id)
        .order_by(SOSReward.created_at, SOSReward.donor_id)
    )).scalars().all()
    return rows


@router.post("/event/{event_id}/rewards/{donor_id}/choice", response_model=SOSRewardOut)
async def record_sos_reward_choice(
    event_id: str,
    donor_id: str,
    req: SOSRewardChoiceIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    """Ghi nhận người dự bị muốn tiếp tục hiến hoặc xin dừng; đây chưa phải giao dịch tiền."""
    event = await db.get(SOSEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    require_self_or_staff(principal, donor_id)
    if principal.is_staff:
        _require_event_facility(event, principal)
    if event.status == "cancelled":
        raise HTTPException(status_code=409, detail="Ca SOS đã bị hủy, không thể cập nhật phương án quà")
    reward = (await db.execute(select(SOSReward).where(
        SOSReward.sos_event_id == event_id, SOSReward.donor_id == donor_id,
    ))).scalar_one_or_none()
    if reward is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy người trong phương án quà")
    if reward.role != "backup" or reward.status != "awaiting_choice":
        raise HTTPException(status_code=409, detail="Chỉ người dự bị đang chờ mới nhận được lựa chọn này")

    reward.decision_at = datetime.now(timezone.utc)
    if req.choice == "continue":
        reward.status = "awaiting_donation"
    else:
        reward.status = "compensation_proposed"
        reward.proposed_amount_vnd = 30_000

    await audit.record(db, principal.subject, audit.SOS_REWARD_CHOICE, {
        "event_id": event_id, "donor_id": donor_id,
        "choice": req.choice, "mock_only": True,
    })
    await db.commit()
    await db.refresh(reward)
    return reward


@router.post("/event/{event_id}/rewards/{donor_id}/donation", response_model=SOSRewardOut)
async def confirm_sos_reward_donation(
    event_id: str,
    donor_id: str,
    req: SOSRewardDonationIn,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Ghi nhận xác nhận của nhân viên cơ sở trong demo; không nhận giấy tờ y tế hay phát voucher thật."""
    event = await db.scalar(
        select(SOSEvent).where(SOSEvent.id == event_id).with_for_update()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    _require_event_facility(event, principal)
    if event.status == "cancelled":
        raise HTTPException(status_code=409, detail="Ca SOS đã bị hủy, không thể cập nhật kết quả hiến")
    accepted_response = (await db.execute(select(SOSResponse.id).where(
        SOSResponse.sos_event_id == event_id,
        SOSResponse.donor_id == donor_id,
        SOSResponse.outcome == "accepted",
    ))).scalar_one_or_none()
    if accepted_response is None:
        raise HTTPException(status_code=409, detail="Chỉ xác nhận thưởng cho người đã nhận lời SOS")

    reward = (await db.execute(select(SOSReward).where(
        SOSReward.sos_event_id == event_id, SOSReward.donor_id == donor_id,
    ))).scalar_one_or_none()
    if reward is None:
        existing_rewards = (await db.execute(select(SOSReward.id).where(
            SOSReward.sos_event_id == event_id,
        ).limit(1))).scalar_one_or_none()
        reward = SOSReward(
            id=str(uuid.uuid4()),
            sos_event_id=event_id,
            donor_id=donor_id,
            role="backup" if existing_rewards else "primary",
            status="awaiting_donation",
            proposed_amount_vnd=None,
            created_at=datetime.now(timezone.utc),
        )
        db.add(reward)
        await db.flush()
    if reward.status != "awaiting_donation":
        raise HTTPException(status_code=409, detail="Người hiến chưa ở trạng thái chờ xác nhận hiến")

    now = datetime.now(timezone.utc)
    reward.decision_at = now
    if req.donated:
        donor = await db.get(Donor, donor_id)
        if donor is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ người hiến")
        last_donation_at = donor.last_donation_at
        if last_donation_at is not None and last_donation_at.tzinfo is None:
            last_donation_at = last_donation_at.replace(tzinfo=timezone.utc)
        if last_donation_at is None or last_donation_at < now:
            donor.last_donation_at = now
        reward.status = "mock_ready"
        reward.proposed_amount_vnd = 100_000 if reward.role == "primary" else 80_000
        reward.donation_confirmed_at = now
        reward.donation_confirmed_by = principal.subject
    else:
        reward.status = "not_completed"
        reward.proposed_amount_vnd = None

    await audit.record(db, principal.subject, audit.SOS_REWARD_CONFIRM, {
        "event_id": event_id, "donor_id": donor_id,
        "donated": req.donated, "role": reward.role,
        "mock_only": True,
        "confirmation_source": "facility_attestation",
    })
    await db.commit()
    await db.refresh(reward)
    return reward


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


@router.get("/responders/map")
async def accepted_responder_map_cells(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_staff),
):
    """Return coarse H3 cells for accepted SOS responders, without donor IDs or contacts."""
    stmt = (
        select(
            SOSResponse.location_cell.label("h3_cell"),
            func.count(func.distinct(SOSResponse.donor_id)).label("count"),
        )
        .join(SOSEvent, SOSEvent.id == SOSResponse.sos_event_id)
        .where(
            SOSResponse.outcome == "accepted",
            SOSResponse.location_cell.is_not(None),
            SOSEvent.status.in_(("open", "fulfilled")),
        )
        .group_by(SOSResponse.location_cell)
    )
    if principal.role != "admin":
        stmt = stmt.where(SOSEvent.facility_id == principal.facility_id)

    rows = (await db.execute(stmt)).all()
    cells = []
    for row in rows:
        lat, lon = h3.cell_to_latlng(row.h3_cell)
        cells.append({
            "h3_cell": row.h3_cell,
            "lat": lat,
            "lon": lon,
            "count": row.count,
        })

    await audit.record(db, principal.subject, audit.DONOR_SEARCH, {
        "mode": "accepted_sos_map", "cells": len(cells),
    })
    await db.commit()
    return cells


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

    event = await db.scalar(
        select(SOSEvent).where(SOSEvent.id == event_id).with_for_update()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện SOS")
    if event.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail="Ca SOS đã đóng, không nhận phản hồi mới")

    outcome = req.resolved_outcome
    if outcome not in ("accepted", "declined", "no_show"):
        raise HTTPException(
            status_code=422,
            detail="outcome phải là accepted | declined | no_show",
        )

    if req.share_location is True:
        if outcome != "accepted":
            raise HTTPException(status_code=422, detail="Chỉ chia sẻ vị trí sau khi nhận lời SOS")
        if req.latitude is None or req.longitude is None:
            raise HTTPException(status_code=422, detail="Thiếu tọa độ GPS đã được người hiến cho phép chia sẻ")
        if principal.is_staff and not settings.local_auth_bypass and principal.subject != req.donor_id:
            raise HTTPException(status_code=403, detail="Chỉ người hiến mới có thể đồng ý chia sẻ vị trí của mình")
    elif req.latitude is not None or req.longitude is not None:
        raise HTTPException(status_code=422, detail="Tọa độ GPS chỉ được gửi khi người hiến đã đồng ý chia sẻ")

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
    if req.share_location is not None:
        response.location_sharing_consented = req.share_location
        response.location_shared_at = now if req.share_location else None
        response.location_latitude = req.latitude if req.share_location else None
        response.location_longitude = req.longitude if req.share_location else None
        response.location_cell = (
            h3.latlng_to_cell(req.latitude, req.longitude, settings.h3_resolution)
            if req.share_location and req.latitude is not None and req.longitude is not None
            else None
        )
    if not accepted:
        response.location_sharing_consented = False
        response.location_shared_at = None
        response.location_latitude = None
        response.location_longitude = None
        response.location_cell = None
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
    # The clinical request is fulfilled once its requested number of donors
    # accepts. Reward confirmation happens later, after the hospital verifies
    # an actual donation.
    completion_threshold = max(event.target_count or 1, 1)
    if event.accept_count >= completion_threshold:
        # The response pool is ready; stop the scheduler from inviting more donors.
        event.status = "fulfilled"
    elif event.status == "fulfilled":
        # A donor retracts before a reward plan is recorded; reopen the campaign.
        event.status = "open"

    await audit.record(db, req.donor_id, audit.SOS_RESPOND, {
        "event_id": event_id, "outcome": outcome, "ring": event.ring,
        "shared_contact": bool(accepted and req.contact_phone),
        "shared_location": bool(accepted and req.share_location is True),
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
        "location_sharing_consented": response.location_sharing_consented,
    }
