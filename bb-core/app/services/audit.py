"""
BB-Core — Nhật ký ghi vết chuỗi băm (append-only).

Bảng `audit_log` có từ đầu nhưng KHÔNG endpoint nào ghi vào — nghĩa là cho tới
P4, mọi truy vấn danh sách người hiến đều không để lại dấu vết nào.

Mỗi dòng băm cả dòng trước nó, nên sửa hay xoá một dòng ở giữa sẽ làm gãy chuỗi
và `verify_chain` chỉ ra ngay dòng đầu tiên bị hỏng. Đây là thứ hội đồng và bên
thanh tra cần: không chứng minh được "chưa ai sửa", nhưng chứng minh được "nếu
có sửa thì phát hiện được".

Ghi nhật ký KHÔNG BAO GIỜ được làm hỏng nghiệp vụ: nếu ghi lỗi thì nuốt lỗi và
để việc chính chạy tiếp — mất một dòng nhật ký còn hơn chặn một ca cấp cứu.
"""

from __future__ import annotations

import json
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AuditLog

log = logging.getLogger("bb-core.audit")

# Khoá tư vấn của Postgres cho chuỗi băm. Số bất kỳ, chỉ cần cả tiến trình
# dùng chung một giá trị.
_CHAIN_LOCK_KEY = 0x_B10D_B11B

# Hành động được ghi vết. Đặt hằng số để không gõ sai chuỗi ở mỗi nơi gọi.
LOGIN = "auth.login"
LOGIN_FAILED = "auth.login_failed"
DONOR_REGISTER = "donor.register"
DONOR_VERIFY = "donor.verify"
DONOR_SEARCH = "donor.search"
DONOR_LIST = "donor.list"
SOS_OPEN = "sos.open"
SOS_ESCALATE = "sos.escalate"
SOS_COMPLETE = "sos.complete"
SOS_RESPOND = "sos.respond"
SOS_LOCATION_REVEAL = "sos.location_reveal"
CONTACT_REVEAL = "sos.contact_reveal"
SOS_REWARD_SELECT = "sos.reward_select"
SOS_REWARD_CHOICE = "sos.reward_choice"
SOS_REWARD_CONFIRM = "sos.reward_confirm"


def compute_hash(prev_hash: Optional[str], actor: str, action: str,
                 payload: dict, at: datetime) -> str:
    """
    Băm một dòng nhật ký cùng dòng trước nó.

    Dùng `json.dumps(sort_keys=True)` chứ không dùng `repr` của dict: repr thay
    đổi theo phiên bản Python và theo thứ tự chèn, nên chuỗi băm sẽ không kiểm
    lại được sau này.
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    data = f"{prev_hash or ''}|{actor}|{action}|{body}|{at.isoformat()}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


async def record(
    db: AsyncSession,
    actor: str,
    action: str,
    payload: Optional[dict] = None,
) -> Optional[AuditLog]:
    """
    Thêm một dòng vào chuỗi. Trả về dòng vừa ghi, hoặc None nếu ghi hỏng.

    `actor` là mã chủ thể (mã tài khoản hoặc mã người hiến), KHÔNG phải họ tên.
    `payload` không được chứa dữ liệu nhận dạng trực tiếp — chỉ mã và số đếm.
    """
    try:
        payload = payload or {}
        at = datetime.now(timezone.utc)

        # Ghi trong một SAVEPOINT riêng.
        #
        # Nuốt lỗi không thôi thì KHÔNG đủ: nếu `flush()` hỏng, giao dịch đang ở
        # trạng thái abort và dòng AuditLog vẫn nằm trong session, nên `commit()`
        # kế tiếp của bên gọi (ví dụ ngay sau `donor.verified = True`) nổ
        # `PendingRollbackError` — đúng kiểu hỏng mà docstring nói module này ngăn.
        # SAVEPOINT cho phép huỷ riêng phần ghi nhật ký, giữ nguyên việc chính.
        async with db.begin_nested():
            # Khoá đầu chuỗi trong suốt giao dịch.
            #
            # Không khoá thì hai request đọc cùng một đầu chuỗi rồi cùng chèn dòng
            # mang cùng `prev_hash`; `verify_chain` sau đó báo "có dòng bị xoá hoặc
            # chèn" vĩnh viễn — báo động giả do đồng thời, không phải do bị sửa.
            # (SQLite trong test chạy tuần tự nên bỏ qua được.)
            if db.bind is not None and db.bind.dialect.name == "postgresql":
                await db.execute(text("SELECT pg_advisory_xact_lock(:k)"),
                                 {"k": _CHAIN_LOCK_KEY})

            prev = (await db.execute(
                select(AuditLog).order_by(desc(AuditLog.at), desc(AuditLog.id)).limit(1)
            )).scalar_one_or_none()
            prev_hash = prev.hash if prev else None

            entry = AuditLog(
                id=str(uuid.uuid4()),
                prev_hash=prev_hash,
                hash=compute_hash(prev_hash, actor, action, payload, at),
                actor=actor,
                action=action,
                payload_json=payload,
                at=at,
            )
            db.add(entry)
            await db.flush()
        return entry
    except Exception as exc:                      # noqa: BLE001 — xem docstring module
        log.warning("Không ghi được nhật ký %s cho %s: %s", action, actor, exc)
        return None


async def verify_chain(db: AsyncSession, limit: int = 10_000) -> dict:
    """
    Kiểm tra tính toàn vẹn của chuỗi.

    Trả về vị trí dòng hỏng đầu tiên, hoặc `ok=True` nếu chuỗi liền mạch.
    """
    rows = (await db.execute(
        select(AuditLog).order_by(AuditLog.at, AuditLog.id).limit(limit)
    )).scalars().all()

    prev_hash: Optional[str] = None
    for index, row in enumerate(rows):
        at = row.at if row.at.tzinfo else row.at.replace(tzinfo=timezone.utc)
        expected = compute_hash(prev_hash, row.actor, row.action, row.payload_json or {}, at)

        if row.prev_hash != prev_hash:
            return {"ok": False, "checked": index, "total": len(rows),
                    "broken_at": row.id,
                    "reason": "prev_hash không khớp dòng liền trước — có dòng bị xoá hoặc chèn"}
        if row.hash != expected:
            return {"ok": False, "checked": index, "total": len(rows),
                    "broken_at": row.id,
                    "reason": "hash không khớp nội dung — dòng này đã bị sửa"}
        prev_hash = row.hash

    return {"ok": True, "checked": len(rows), "total": len(rows),
            "head_hash": prev_hash, "reason": "Chuỗi liền mạch"}
