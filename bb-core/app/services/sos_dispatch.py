"""
BB-Core — Chọn người hiến cho một vòng SOS và gửi lời kêu gọi.

Tách khỏi `api/sos.py` vì ba nơi cùng cần: endpoint mở lời kêu gọi, endpoint leo
thang thủ công, và bộ lập lịch tự nâng vòng.

Quy tắc quan trọng: **mỗi người hiến chỉ được gọi MỘT lần cho mỗi sự kiện**. Vòng
sau chỉ gọi những người vòng trước chưa với tới — nếu không, người ở ngay cạnh
bệnh viện sẽ bị réo lại ở cả bốn vòng.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import h3
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import Donor, Facility, SOSEvent, SOSNotification
from app.services.compatibility import is_compatible
from app.services.eligibility import donation_eligibility, eligible_cutoff
from app.services.push import PushMessage, get_push_provider

# Bán kính tìm kiếm theo vòng, tính bằng số ô H3 (res 7 ≈ 1,2 km/ô).
# -1 = bỏ ràng buộc vị trí (vòng 3: toàn thành phố).
RING_DISK_K = [0, 1, 2, -1]

RING_LABEL = [
    "Vòng 0 (~1 km, cùng nhóm máu)",
    "Vòng 1 (~3 km, nhóm tương hợp)",
    "Vòng 2 (~5 km, mở rộng)",
    "Vòng 3 (toàn thành phố)",
]

COMPONENT_LABEL = {
    "WB": "máu toàn phần",
    "RBC": "khối hồng cầu",
    "PLT": "khối tiểu cầu",
    "FFP": "huyết tương",
    "CRYO": "kết tủa lạnh",
}

URGENCY_LABEL = {
    "emergency": "CẤP CỨU",
    "urgent": "Cấp bách",
    "routine": "Luân chuyển",
}


@dataclass
class DispatchResult:
    ring: int
    matched: int = 0            # số người hợp lệ ở vòng này
    notified: int = 0           # số người thực sự được gọi (chưa gọi ở vòng trước)
    already_notified: int = 0
    failures: list[str] = field(default_factory=list)


# ── Chọn người hiến ───────────────────────────────────────────────

def cells_for_ring(h3_cell: Optional[str], ring: int) -> Optional[list[str]]:
    """Tập ô H3 cần quét cho một vòng, hoặc None nếu không giới hạn vị trí."""
    k = RING_DISK_K[max(0, min(ring, 3))]
    if k < 0 or not h3_cell:
        return None
    return list(h3.grid_disk(h3_cell, k))


async def facility_cell(db: AsyncSession, facility_id: Optional[str]) -> Optional[str]:
    """
    Ô lưới H3 của cơ sở phát yêu cầu.

    `Facility` chỉ có cột `geom` (PostGIS POINT), KHÔNG có `lat`/`lon`; phải giải
    mã WKB qua shapely chứ không truy cập thuộc tính thẳng.
    """
    if not facility_id:
        return None
    facility = await db.get(Facility, facility_id)
    if not facility or facility.geom is None:
        return None
    point = to_shape(facility.geom)
    return h3.latlng_to_cell(point.y, point.x, settings.h3_resolution)


def donor_matches(donor: Donor, abo: Optional[str], rh: Optional[str],
                  component: str, ring: int,
                  recipient_sex: Optional[str] = None,
                  recipient_age: Optional[int] = None) -> tuple[bool, str]:
    """
    Người hiến này có gọi được cho ca bệnh nhóm `abo``rh` không?

    Vòng 0 chỉ lấy đúng nhóm máu; từ vòng 1 mới mở sang nhóm tương hợp theo bảng
    ABO/RhD trong `services/compatibility.py`.
    """
    if not abo or not rh:
        return True, "không lọc theo nhóm máu"

    same_type = donor.abo.value == abo and donor.rh.value == rh
    if ring == 0:
        return same_type, "cùng nhóm máu" if same_type else "vòng 0 chỉ nhận cùng nhóm máu"

    return is_compatible(
        donor.abo.value,
        donor.rh.value,
        abo,
        rh,
        component,
        recipient_sex,
        recipient_age,
    )


def apply_geocell_filter(stmt, cells: Optional[list[str]], now: datetime):
    """
    Lọc theo ô lưới H3 — vị ngữ DUY NHẤT cho cả việc tìm quanh lẫn việc gửi thật.

    Quy tắc: TTL chỉ có nghĩa khi ta đang lọc THEO vị trí. Vòng 0–2 giới hạn theo
    ô lưới nên ô phải còn hạn; vòng 3 là cảnh báo toàn thành phố, không lọc vị trí
    thì cũng không xét TTL.

    Trước đây hai bên tự viết điều kiện riêng và lệch nhau theo cả hai chiều:
    `/sos/donors/nearby` nhận cả TTL NULL (nên đếm nhiều hơn số thật sự được gọi),
    còn ở vòng 3 thì `select_donors` bỏ hẳn lọc TTL trong khi `nearby` vẫn lọc
    (nên đếm ít hơn). Nhân viên nhìn con số nào cũng không đúng với việc sẽ xảy ra.
    """
    if cells is None:
        return stmt
    return stmt.where(Donor.geocell_h3.in_(cells), Donor.geocell_ttl > now)


async def select_donors(
    db: AsyncSession,
    *,
    cell: Optional[str],
    ring: int,
    abo: Optional[str],
    rh: Optional[str],
    component: str,
    recipient_sex: Optional[str] = None,
    recipient_age: Optional[int] = None,
) -> list[Donor]:
    """Người hiến đã xác minh, đúng vùng, tương hợp và đủ khoảng cách hiến."""
    now = datetime.now(timezone.utc)
    cells = cells_for_ring(cell, ring)

    stmt = apply_geocell_filter(
        select(Donor).where(Donor.verified.is_(True)), cells, now)

    # Lọc điều kiện hiến ngay trong SQL — xem ghi chú ở `eligible_cutoff`.
    cutoff = eligible_cutoff(component, now)
    stmt = stmt.where(
        (Donor.last_donation_at.is_(None)) | (Donor.last_donation_at <= cutoff)
    )

    candidates = (await db.execute(stmt)).scalars().all()
    return [d for d in candidates
            if donor_matches(d, abo, rh, component, ring, recipient_sex, recipient_age)[0]
            and donation_eligibility(d.last_donation_at, component=component, now=now)["eligible"]]


# ── Gửi lời kêu gọi ───────────────────────────────────────────────

def build_message(event: SOSEvent, facility_name: Optional[str]) -> tuple[str, str]:
    """Tiêu đề và nội dung thông báo hiển thị trên điện thoại."""
    if event.urgency == "mock_test":
        return (
            "KIỂM THỬ — SOS mô phỏng vòng 0",
            "Thông báo kiểm thử gửi riêng tới thiết bị này. Đây không phải yêu cầu hiến máu thật.",
        )

    blood = f"{event.abo or ''}{event.rh or ''}".strip() or "phù hợp"
    component = COMPONENT_LABEL.get((event.component_code or "WB").upper(),
                                    event.component_code or "máu")
    urgency = URGENCY_LABEL.get(event.urgency or "urgent", "Cần gấp")
    where = facility_name or "một cơ sở y tế gần bạn"

    title = f"{urgency}: cần {blood} — {component}"
    body = f"{where} đang cần {event.target_count} người hiến {blood}. Bạn có thể tới không?"
    return title, body


async def dispatch_ring(db: AsyncSession, event: SOSEvent) -> DispatchResult:
    """
    Gửi lời kêu gọi cho vòng hiện tại của `event`.

    Bỏ qua người đã nhận ở vòng trước. Ghi bảng `sos_notification` TRƯỚC khi đẩy,
    để lời kêu gọi vẫn còn dấu vết kể cả khi kênh đẩy hỏng.
    """
    result = DispatchResult(ring=event.ring)

    donors = await select_donors(
        db,
        cell=event.h3_cell,
        ring=event.ring,
        abo=event.abo,
        rh=event.rh,
        component=(event.component_code or "WB").upper(),
        recipient_sex=event.recipient_sex,
        recipient_age=event.recipient_age,
    )
    result.matched = len(donors)
    if not donors:
        return result

    already = set((await db.execute(
        select(SOSNotification.donor_id).where(SOSNotification.sos_event_id == event.id)
    )).scalars())
    fresh = [d for d in donors if d.id not in already]
    result.already_notified = len(donors) - len(fresh)
    if not fresh:
        return result

    facility = await db.get(Facility, event.facility_id) if event.facility_id else None
    title, body = build_message(event, facility.name if facility else None)

    provider = get_push_provider()
    now = datetime.now(timezone.utc)

    for donor in fresh:
        notification = SOSNotification(
            id=str(uuid.uuid4()),
            sos_event_id=event.id,
            donor_id=donor.id,
            ring=event.ring,
            created_at=now,
            channel=provider.name,
            status="pending",
        )

        # Giữ chỗ TRƯỚC khi đẩy.
        #
        # Tập `already` ở trên chỉ đúng tại thời điểm đọc: bộ lập lịch quét 30 giây
        # một lần còn console thì có nút leo thang tay, hai đường chạy chồng nhau
        # sẽ cùng thấy một người là "chưa gọi". Chỉ mục duy nhất
        # `ix_sos_notif_event_donor` bắt được, nhưng nếu để tới lúc commit thì cả
        # lượt quét đổ và vòng đã tăng mà không ai được gọi. Chèn từng dòng trong
        # SAVEPOINT: ai giữ chỗ trước thì thắng, người kia bỏ qua và đi tiếp.
        db.add(notification)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            db.expunge(notification)
            result.already_notified += 1
            continue

        push = await provider.send(PushMessage(
            token=donor.push_token,
            title=title,
            body=body,
            data={
                "event_id": event.id,
                "ring": str(event.ring),
                "abo": event.abo or "",
                "rh": event.rh or "",
                "component_code": event.component_code or "WB",
                "urgency": event.urgency or "urgent",
                "facility_name": facility.name if facility else "",
            },
        ))

        if push.ok:
            notification.status = "sent"
            notification.delivered_at = now
            result.notified += 1
        else:
            # Vẫn giữ dòng thông báo: app hỏi hộp thư là thấy, và nhật ký ghi vết
            # phải phản ánh cả lần gửi hỏng.
            notification.status = "failed"
            notification.error = push.error
            result.failures.append(push.error or "lỗi không rõ")

        db.add(notification)

    await db.commit()
    return result


async def escalate_event(db: AsyncSession, event: SOSEvent) -> DispatchResult:
    """
    Nâng sự kiện lên vòng kế tiếp và gọi những người mới với tới.

    Leo thang trên CHÍNH sự kiện đó, không tạo sự kiện mới — nhờ vậy lịch sử
    "ai đã được gọi ở vòng nào" nằm gọn trong một hồ sơ.
    """
    # Khoá dòng sự kiện suốt lượt nâng vòng: bộ lập lịch (30 giây/lượt) và nút
    # leo thang tay trên console có thể vào cùng lúc, và nếu cả hai cùng đọc
    # `ring` cũ thì vòng bị nhảy hai bậc mà một bậc không gọi ai.
    if db.bind is not None:
        statement = select(SOSEvent).where(SOSEvent.id == event.id)
        if db.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        locked = (await db.execute(
            statement.execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if locked is None:
            return DispatchResult(ring=event.ring)
        event = locked

    # A donor can fulfill the target after a scheduler or manual caller loaded
    # this event. Recheck the locked, refreshed row before issuing another ring.
    if event.status != "open":
        return DispatchResult(ring=event.ring)

    if event.ring >= 3:
        return DispatchResult(ring=event.ring)

    event.ring += 1
    await db.commit()
    await db.refresh(event)
    return await dispatch_ring(db, event)


async def dispatch_initial_rings(db: AsyncSession, event: SOSEvent) -> tuple[DispatchResult, int]:
    """Try the requested ring, then immediately widen until at least one invite is sent."""
    result = await dispatch_ring(db, event)
    escalations = 0
    while result.notified == 0 and event.ring < 3:
        previous_ring = event.ring
        result = await escalate_event(db, event)
        if event.status != "open" or event.ring <= previous_ring:
            break
        escalations += 1
    return result, escalations
