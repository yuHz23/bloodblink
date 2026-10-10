"""
BB-Core — Kiểm thử ghi vết và ranh giới danh tính (P4).

Hai câu hỏi mà hội đồng sẽ hỏi:
  1. Cơ sở y tế tra danh sách người hiến thì có để lại dấu vết không?
  2. Danh tính người hiến lộ ra lúc nào, cho ai?
"""

from datetime import datetime, timezone

import h3
import pytest_asyncio

from app.config import settings
from app.services import audit
from app.services.auth import create_access_token
from tests.conftest import admin_headers, donor_headers

CELL = h3.latlng_to_cell(10.7626, 106.6602, settings.h3_resolution)


async def add_donor(staff, donor_id, abo="O", rh="+"):
    r = await staff.post("/api/donors/register", json={
        "id": donor_id, "abo": abo, "rh": rh, "h3_cell": CELL})
    await staff.post(f"/api/donors/{donor_id}/verify", json={"verified": True})
    return r.json()


async def open_event(staff, **kw):
    payload = {"component_code": "WB", "abo": "O", "rh": "+",
               "urgency": "emergency", "qty": 2, "ring": 0, "h3_cell": CELL}
    payload.update(kw)
    return (await staff.post("/api/sos/event", json=payload)).json()


class TestHashChain:

    def test_hash_changes_when_payload_changes(self):
        now = datetime.now(timezone.utc)
        a = audit.compute_hash(None, "user-1", audit.DONOR_SEARCH, {"results": 5}, now)
        b = audit.compute_hash(None, "user-1", audit.DONOR_SEARCH, {"results": 6}, now)
        assert a != b

    def test_hash_is_order_independent_for_dict_keys(self):
        """Cùng nội dung, khác thứ tự khoá → phải ra cùng một băm, nếu không
        chuỗi không kiểm lại được sau khi dữ liệu đi vòng qua JSON."""
        now = datetime.now(timezone.utc)
        a = audit.compute_hash(None, "u", "act", {"a": 1, "b": 2}, now)
        b = audit.compute_hash(None, "u", "act", {"b": 2, "a": 1}, now)
        assert a == b

    def test_chain_links_to_previous(self):
        now = datetime.now(timezone.utc)
        first = audit.compute_hash(None, "u", "act", {}, now)
        second = audit.compute_hash(first, "u", "act", {}, now)
        third_without_first = audit.compute_hash(None, "u", "act", {}, now)
        assert second != third_without_first, "đổi dòng trước phải đổi băm dòng sau"


class TestAuditTrail:

    async def test_search_leaves_a_trace(self, staff, db_session):
        await add_donor(staff, "d-001")
        await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL, "abo": "O"})

        rows = (await staff.get("/api/audit", params={"action": audit.DONOR_SEARCH},
                                headers=admin_headers())).json()
        assert len(rows) >= 1
        assert rows[0]["payload"]["h3_cell"] == CELL
        assert rows[0]["payload"]["abo"] == "O"

    async def test_verify_records_who_and_whom(self, staff):
        await add_donor(staff, "d-001")
        rows = (await staff.get("/api/audit", params={"action": audit.DONOR_VERIFY},
                                headers=admin_headers())).json()
        assert rows[0]["payload"]["donor_id"] == "d-001"
        assert rows[0]["actor"] == "user-choray"

    async def test_failed_login_is_recorded(self, client):
        await client.post("/api/auth/login",
                          json={"username": "choray", "password": "doan-mo"})
        rows = (await client.get("/api/audit", params={"action": audit.LOGIN_FAILED},
                                 headers=admin_headers())).json()
        assert len(rows) >= 1
        assert rows[0]["actor"] == "choray"

    async def test_chain_verifies_clean(self, staff):
        await add_donor(staff, "d-001")
        await open_event(staff)
        result = (await staff.get("/api/audit/verify", headers=admin_headers())).json()
        assert result["ok"] is True, result["reason"]
        assert result["checked"] >= 3

    async def test_tampering_is_detected(self, staff, db_session):
        """Sửa một dòng ở giữa chuỗi phải bị phát hiện."""
        from sqlalchemy import select
        from app.models.database import AuditLog

        await add_donor(staff, "d-001")
        await open_event(staff)

        rows = (await db_session.execute(
            select(AuditLog).order_by(AuditLog.at, AuditLog.id))).scalars().all()
        assert len(rows) >= 2

        victim = rows[len(rows) // 2]
        victim.payload_json = {**(victim.payload_json or {}), "results": 999999}
        await db_session.commit()

        result = (await staff.get("/api/audit/verify", headers=admin_headers())).json()
        assert result["ok"] is False
        assert result["broken_at"] == victim.id
        assert "đã bị sửa" in result["reason"]

    async def test_audit_is_admin_only(self, staff):
        assert (await staff.get("/api/audit")).status_code == 403
        assert (await staff.get("/api/audit/verify")).status_code == 403
        assert (await staff.get("/api/audit",
                                headers=donor_headers("d-001"))).status_code == 403


class TestContactReveal:
    """Danh tính chỉ xuất hiện khi người hiến nhận lời."""

    async def test_declining_does_not_store_contact(self, staff):
        await add_donor(staff, "d-001")
        ev = await open_event(staff)

        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "declined",
                               "contact_phone": "0900000000"},
                         headers=donor_headers("d-001"))

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/responses",
                                headers=admin_headers())).json()
        assert rows == [], "người từ chối không được có mặt, càng không được lưu số"

    async def test_accepting_reveals_contact_to_facility(self, staff):
        await add_donor(staff, "d-001")
        ev = await open_event(staff)

        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted",
                               "contact_phone": "0912345678",
                               "contact_note": "có mặt sau 30 phút"},
                         headers=donor_headers("d-001"))

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/responses",
                                headers=admin_headers())).json()
        assert len(rows) == 1
        assert rows[0]["donor_id"] == "d-001"
        assert rows[0]["contact_phone"] == "0912345678"
        assert rows[0]["contact_note"] == "có mặt sau 30 phút"
        assert rows[0]["blood_type"] == "O+"

    async def test_accepting_without_phone_is_allowed(self, staff):
        """Chia sẻ số là tuỳ chọn — không nhập vẫn nhận lời được."""
        await add_donor(staff, "d-001")
        ev = await open_event(staff)
        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted"},
                         headers=donor_headers("d-001"))

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/responses",
                                headers=admin_headers())).json()
        assert len(rows) == 1
        assert rows[0]["contact_phone"] is None

    async def test_donor_cannot_read_responders(self, staff):
        ev = await open_event(staff)
        r = await staff.get(f"/api/sos/event/{ev['id']}/responses",
                            headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_reveal_is_audited(self, staff):
        await add_donor(staff, "d-001")
        ev = await open_event(staff)
        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted",
                               "contact_phone": "0912345678"},
                         headers=donor_headers("d-001"))
        await staff.get(f"/api/sos/event/{ev['id']}/responses",
                        headers=admin_headers())

        rows = (await staff.get("/api/audit", params={"action": audit.CONTACT_REVEAL},
                                headers=admin_headers())).json()
        assert len(rows) == 1
        assert rows[0]["payload"]["event_id"] == ev["id"]
        assert rows[0]["payload"]["with_phone"] == 1

    async def test_other_facility_cannot_read_responders(self, staff):
        """Cơ sở khác không xem được người nhận lời của lời kêu gọi không phải của mình."""
        ev = await open_event(staff, facility_id="fac-bv-tmhh")

        other = create_access_token("user-khac", "facility_staff", "fac-bv-ung-buou")
        r = await staff.get(f"/api/sos/event/{ev['id']}/responses",
                            headers={"Authorization": f"Bearer {other}"})
        assert r.status_code == 403
