"""
BB-Core — Kiểm thử leo thang tự động và kênh giao lời kêu gọi (P2).

Trước P2, bốn mốc T+0/10/25/45 phút chỉ là chú thích trong mã: không có gì tự
nâng vòng, và lời kêu gọi không có đường nào tới điện thoại.
"""

from datetime import datetime, timezone, timedelta

import h3

from app.config import settings
from app.services.scheduler import due_ring, escalate_due_events
from tests.conftest import donor_headers

CELL = h3.latlng_to_cell(10.7626, 106.6602, settings.h3_resolution)
NEIGHBOUR = [c for c in h3.grid_disk(CELL, 1) if c != CELL][0]
RING2_CELL = [c for c in h3.grid_disk(CELL, 2) if c not in h3.grid_disk(CELL, 1)][0]
FAR_CELL = h3.latlng_to_cell(10.95, 106.90, settings.h3_resolution)


async def add_donor(staff, donor_id, abo="O", rh="+", cell=CELL):
    r = await staff.post("/api/donors/register", json={
        "id": donor_id, "abo": abo, "rh": rh, "h3_cell": cell})
    assert r.status_code == 200, r.text
    await staff.post(f"/api/donors/{donor_id}/verify", json={"verified": True})
    return r.json()


async def open_event(staff, **overrides):
    payload = {"component_code": "WB", "abo": "O", "rh": "+",
               "urgency": "emergency", "qty": 5, "ring": 0, "h3_cell": CELL}
    payload.update(overrides)
    r = await staff.post("/api/sos/event", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestDueRing:
    """Mốc leo thang lấy từ settings.sos_rings = [0, 10, 25, 45] phút."""

    def test_ring_by_elapsed_time(self):
        now = datetime.now(timezone.utc)
        assert due_ring(now, now) == 0
        assert due_ring(now - timedelta(minutes=5), now) == 0
        assert due_ring(now - timedelta(minutes=10), now) == 1
        assert due_ring(now - timedelta(minutes=24), now) == 1
        assert due_ring(now - timedelta(minutes=25), now) == 2
        assert due_ring(now - timedelta(minutes=45), now) == 3
        assert due_ring(now - timedelta(hours=3), now) == 3, "không có vòng nào quá 3"

    def test_naive_timestamp_treated_as_utc(self):
        """Postgres trả về datetime không múi giờ — không được nổ ở đây."""
        naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
        assert due_ring(naive) == 2


class TestNotificationFanout:

    async def test_event_notifies_matching_donors(self, staff):
        await add_donor(staff, "d-001", "O", "+")
        await add_donor(staff, "d-002", "A", "+")      # sai nhóm ở vòng 0

        ev = await open_event(staff)
        assert ev["donors_notified"] == 1

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/notifications")).json()
        assert [r["donor_id"] for r in rows] == ["d-001"]
        assert rows[0]["ring"] == 0
        assert rows[0]["channel"] == "store"
        assert rows[0]["status"] == "sent"

    async def test_donor_is_never_called_twice_for_one_event(self, staff):
        """Người ngay cạnh bệnh viện không được réo lại ở cả bốn vòng."""
        await add_donor(staff, "d-near", "O", "+", cell=CELL)
        await add_donor(staff, "d-mid", "O", "+", cell=NEIGHBOUR)

        ev = await open_event(staff)
        assert ev["donors_notified"] == 1              # chỉ d-near

        r = await staff.post(f"/api/sos/event/{ev['id']}/escalate")
        assert r.status_code == 200
        assert r.json()["ring"] == 1
        assert r.json()["donors_notified"] == 1        # chỉ d-mid, không gọi lại d-near

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/notifications")).json()
        assert len(rows) == 2
        assert {r["donor_id"]: r["ring"] for r in rows} == {"d-near": 0, "d-mid": 1}

    async def test_escalation_widens_blood_type_not_just_radius(self, staff):
        """Vòng 0 chỉ cùng nhóm; từ vòng 1 mở sang nhóm tương hợp (A+ → AB+)."""
        await add_donor(staff, "d-a", "A", "+", cell=CELL)

        ev = await open_event(staff, abo="AB", rh="+", component_code="RBC")
        assert ev["donors_notified"] == 0

        r = await staff.post(f"/api/sos/event/{ev['id']}/escalate")
        assert r.json()["donors_notified"] == 1

    async def test_escalate_stops_at_ring_3(self, staff):
        ev = await open_event(staff, ring=3)
        r = await staff.post(f"/api/sos/event/{ev['id']}/escalate")
        assert r.status_code == 409

    async def test_cannot_escalate_fulfilled_event(self, staff):
        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff, qty=1)
        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted"})

        r = await staff.post(f"/api/sos/event/{ev['id']}/escalate")
        assert r.status_code == 409
        assert "fulfilled" in r.json()["detail"]

    async def test_donor_cannot_escalate(self, staff):
        ev = await open_event(staff)
        r = await staff.post(f"/api/sos/event/{ev['id']}/escalate",
                             headers=donor_headers("d-001"))
        assert r.status_code == 403


class TestSosInbox:
    """Kênh giao lời kêu gọi khi chưa có Firebase."""

    async def test_donor_sees_own_call(self, staff):
        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff)

        r = await staff.get("/api/donors/d-001/sos-inbox", headers=donor_headers("d-001"))
        assert r.status_code == 200
        inbox = r.json()
        assert len(inbox) == 1
        assert inbox[0]["event_id"] == ev["id"]
        assert inbox[0]["blood_type"] == "O+"
        assert inbox[0]["component_code"] == "WB"
        assert "CẤP CỨU" in inbox[0]["title"]
        assert inbox[0]["target_count"] == 5

    async def test_inbox_is_private(self, staff):
        await add_donor(staff, "d-001", "O", "+")
        await open_event(staff)
        r = await staff.get("/api/donors/d-001/sos-inbox", headers=donor_headers("d-002"))
        assert r.status_code == 403

    async def test_answering_clears_the_inbox(self, staff):
        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff)

        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "declined"},
                         headers=donor_headers("d-001"))

        inbox = (await staff.get("/api/donors/d-001/sos-inbox",
                                 headers=donor_headers("d-001"))).json()
        assert inbox == []

        # Vẫn tra lại được lịch sử
        history = (await staff.get("/api/donors/d-001/sos-inbox?include_read=true",
                                   headers=donor_headers("d-001"))).json()
        assert len(history) == 1
        assert history[0]["status"] == "read"

    async def test_fulfilled_event_disappears_from_inbox(self, staff):
        """Đủ người rồi thì thôi réo những người còn lại."""
        await add_donor(staff, "d-001", "O", "+")
        await add_donor(staff, "d-002", "O", "+")
        ev = await open_event(staff, qty=1)

        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted"},
                         headers=donor_headers("d-001"))

        inbox = (await staff.get("/api/donors/d-002/sos-inbox",
                                 headers=donor_headers("d-002"))).json()
        assert inbox == []


class TestPushToken:

    async def test_register_and_revoke_device(self, staff):
        await add_donor(staff, "d-001", "O", "+")

        r = await staff.put("/api/donors/d-001/push-token",
                            json={"push_token": "fcm-abc-123", "platform": "android"},
                            headers=donor_headers("d-001"))
        assert r.status_code == 200

        nearby = (await staff.get("/api/sos/donors/nearby",
                                  params={"h3_cell": CELL})).json()
        me = next(d for d in nearby["donors"] if d["donor_id"] == "d-001")
        assert me["reachable_by_push"] is True

        await staff.put("/api/donors/d-001/push-token", json={"push_token": ""},
                        headers=donor_headers("d-001"))
        nearby = (await staff.get("/api/sos/donors/nearby",
                                  params={"h3_cell": CELL})).json()
        me = next(d for d in nearby["donors"] if d["donor_id"] == "d-001")
        assert me["reachable_by_push"] is False

    async def test_donor_cannot_set_someone_elses_token(self, staff):
        await add_donor(staff, "d-002", "O", "+")
        r = await staff.put("/api/donors/d-002/push-token",
                            json={"push_token": "cua-nguoi-khac"},
                            headers=donor_headers("d-001"))
        assert r.status_code == 403


class TestScheduler:
    """Bộ quét tự nâng vòng — phần khiến mốc T+10/25/45 thành việc thật."""

    async def test_scheduler_escalates_overdue_event(self, staff, db_session):
        from app.models.database import SOSEvent

        await add_donor(staff, "d-near", "O", "+", cell=CELL)
        await add_donor(staff, "d-mid", "O", "+", cell=NEIGHBOUR)
        ev = await open_event(staff)

        # Kéo lùi thời điểm mở 30 phút → lẽ ra phải ở vòng 2
        event = await db_session.get(SOSEvent, ev["id"])
        event.opened_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        await db_session.commit()

        escalations = await escalate_due_events(db_session)
        assert escalations == 2, "vòng 0 → 1 → 2"

        await db_session.refresh(event)
        assert event.ring == 2

        rows = (await staff.get(f"/api/sos/event/{ev['id']}/notifications")).json()
        assert {r["donor_id"]: r["ring"] for r in rows} == {"d-near": 0, "d-mid": 1}

    async def test_scheduler_leaves_fresh_event_alone(self, staff, db_session):
        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff)

        assert await escalate_due_events(db_session) == 0

        status = (await staff.get(f"/api/sos/event/{ev['id']}")).json()
        assert status["ring"] == 0

    async def test_scheduler_skips_fulfilled_event(self, staff, db_session):
        from app.models.database import SOSEvent

        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff, qty=1)
        await staff.post(f"/api/sos/event/{ev['id']}/respond",
                         json={"donor_id": "d-001", "response": "accepted"})

        event = await db_session.get(SOSEvent, ev["id"])
        event.opened_at = datetime.now(timezone.utc) - timedelta(minutes=60)
        await db_session.commit()

        assert await escalate_due_events(db_session) == 0

    async def test_scheduler_closes_stale_event(self, staff, db_session):
        from app.models.database import SOSEvent

        await add_donor(staff, "d-001", "O", "+")
        ev = await open_event(staff)

        event = await db_session.get(SOSEvent, ev["id"])
        event.opened_at = (datetime.now(timezone.utc)
                           - timedelta(minutes=settings.sos_event_ttl_minutes + 10))
        await db_session.commit()

        await escalate_due_events(db_session)
        await db_session.refresh(event)
        assert event.status == "expired"

        inbox = (await staff.get("/api/donors/d-001/sos-inbox",
                                 headers=donor_headers("d-001"))).json()
        assert inbox == [], "sự kiện quá hạn không còn nằm trong hộp thư"
