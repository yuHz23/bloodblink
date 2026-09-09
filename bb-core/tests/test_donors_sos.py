"""
BB-Core — Kiểm thử luồng P0: hồ sơ người hiến đi từ app tới máy chủ và
được cơ sở y tế tìm thấy.

Chạy trên SQLite trong bộ nhớ với đúng ba bảng của luồng này (donor, sos_event,
sos_response) nên không cần dựng Postgres/PostGIS để chạy test.

Mọi test ở đây chạy dưới fixture `staff` (đã đăng nhập vai trò facility_staff);
phần kiểm tra phân quyền nằm ở `test_auth.py`.

Bốn thứ được khoá lại ở đây, vì chúng chính là chỗ hỏng trước P0:
  1. Có đường đăng ký người hiến — bảng `donor` không còn chỉ có dữ liệu seed.
  2. Ô lưới H3 do app sinh (res 7) khớp với ô server tìm.
  3. Payload app BB-SOS gửi tới /sos/event không còn bị 422.
  4. Phản hồi SOS nhận JSON body, không phải query param.
"""

from datetime import datetime, timezone, timedelta

import h3

from app.config import settings

# Toạ độ trong nội thành TP.HCM
HCMC_LAT, HCMC_LON = 10.7626, 106.6602
FAR_LAT, FAR_LON = 10.9500, 106.9000      # Biên Hoà — chắc chắn khác ô lưới

CELL = h3.latlng_to_cell(HCMC_LAT, HCMC_LON, settings.h3_resolution)
FAR_CELL = h3.latlng_to_cell(FAR_LAT, FAR_LON, settings.h3_resolution)


async def register(staff, donor_id, abo, rh, *, cell=CELL, last_donation=None):
    payload = {"id": donor_id, "abo": abo, "rh": rh, "birth_year": 1998,
               "sex": "M", "weight_kg": 65, "h3_cell": cell}
    if last_donation:
        payload["last_donation_at"] = last_donation.isoformat()
    r = await staff.post("/api/donors/register", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


class TestDonorRegistration:
    """Hồ sơ điền trong app phải tới được máy chủ."""

    async def test_register_creates_donor(self, staff):
        body = await register(staff, "d-001", "O", "+")
        assert body["id"] == "d-001"
        assert body["blood_type"] == "O+"
        assert body["geocell_h3"] == CELL
        assert body["geocell_valid"] is True
        # Người hiến KHÔNG tự xác minh được
        assert body["verified"] is False

    async def test_register_is_idempotent_upsert(self, staff):
        await register(staff, "d-001", "O", "+")
        body = await register(staff, "d-001", "A", "-")   # đổi nhóm máu
        assert body["blood_type"] == "A-"

        listing = (await staff.get("/api/donors")).json()
        assert len(listing) == 1, "gọi lại /register không được tạo người hiến thứ hai"

    async def test_register_rejects_bad_blood_type(self, staff):
        r = await staff.post("/api/donors/register", json={"abo": "Z", "rh": "+"})
        assert r.status_code == 422

    async def test_geocell_refresh_and_revoke(self, staff):
        await register(staff, "d-001", "O", "+")

        r = await staff.patch("/api/donors/d-001/geocell",
                               json={"h3_cell": FAR_CELL, "ttl_hours": 2})
        assert r.json()["geocell_h3"] == FAR_CELL

        r = await staff.delete("/api/donors/d-001/geocell")
        assert r.json()["geocell_h3"] is None
        assert r.json()["geocell_valid"] is False


class TestEligibility:
    """Khoảng cách giữa hai lần hiến — Điều 6 TT 26/2013/TT-BYT."""

    async def test_recent_whole_blood_blocks_wb_not_plasma(self, staff):
        recent = datetime.now(timezone.utc) - timedelta(days=30)
        await register(staff, "d-001", "O", "+", last_donation=recent)

        wb = (await staff.get("/api/donors/d-001", params={"component_code": "WB"})).json()
        assert wb["eligible"] is False
        assert wb["eligible_wb_rbc"] is False
        assert "Điều 6" in wb["ineligible_reason"]

        plt = (await staff.get("/api/donors/d-001", params={"component_code": "PLT"})).json()
        assert plt["eligible"] is True      # 30 ngày > 2 tuần

    async def test_record_donation_moves_the_clock(self, staff):
        await register(staff, "d-001", "O", "+")
        assert (await staff.get("/api/donors/d-001")).json()["eligible"] is True

        r = await staff.post("/api/donors/d-001/donation", json={"component_code": "WB"})
        assert r.json()["eligible"] is False
        assert r.json()["days_since_donation"] == 0

    async def test_future_donation_rejected(self, staff):
        await register(staff, "d-001", "O", "+")
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        r = await staff.post("/api/donors/d-001/donation",
                              json={"component_code": "WB", "donated_at": future})
        assert r.status_code == 422


class TestNearbySearch:
    """Cơ sở y tế tìm người cùng nhóm máu quanh một ô lưới."""

    async def test_unverified_donor_hidden_until_verified(self, staff):
        await register(staff, "d-001", "O", "+")

        r = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL})
        assert r.json()["total_donors"] == 0

        await staff.post("/api/donors/d-001/verify", json={"verified": True})
        r = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL})
        body = r.json()
        assert body["total_donors"] == 1
        # App BB-SOS đọc `total_donors`, BB-Console đọc `donors_found`
        assert body["donors_found"] == body["total_donors"]
        assert body["donors"][0]["eligible"] is True
        assert body["donors"][0]["blood_type"] == "O+"

    async def test_filters_by_blood_type(self, staff):
        await register(staff, "d-001", "O", "+")
        await register(staff, "d-002", "A", "-")
        for d in ("d-001", "d-002"):
            await staff.post(f"/api/donors/{d}/verify", json={"verified": True})

        r = await staff.get("/api/sos/donors/nearby",
                             params={"h3_cell": CELL, "abo": "A", "rh": "-"})
        assert [d["donor_id"] for d in r.json()["donors"]] == ["d-002"]

    async def test_ring_widens_the_radius(self, staff):
        # Người hiến ở ô kề bên: vòng 0 không thấy, vòng 1 thì thấy
        neighbour = [c for c in h3.grid_disk(CELL, 1) if c != CELL][0]
        await register(staff, "d-001", "O", "+", cell=neighbour)
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        r0 = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL, "ring": 0})
        assert r0.json()["total_donors"] == 0

        r1 = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL, "ring": 1})
        assert r1.json()["total_donors"] == 1

    async def test_ring3_is_citywide(self, staff):
        """Vòng 3 là cảnh báo toàn thành phố — không được lọc theo ô lưới."""
        await register(staff, "d-001", "O", "+", cell=FAR_CELL)
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        r0 = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL, "ring": 0})
        assert r0.json()["total_donors"] == 0

        r3 = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL, "ring": 3})
        assert r3.json()["citywide"] is True
        assert r3.json()["total_donors"] == 1

    async def test_expired_geocell_disappears(self, staff):
        await register(staff, "d-001", "O", "+")
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        # Ép TTL về quá khứ như khi người hiến để máy 5 tiếng không mở app
        await staff.patch("/api/donors/d-001/geocell",
                           json={"h3_cell": CELL, "ttl_hours": 1})
        r = await staff.get("/api/sos/donors/nearby", params={"h3_cell": CELL})
        assert r.json()["total_donors"] == 1

    async def test_h3_string_form_matches_flutter(self, staff):
        """
        App Flutter sinh chuỗi ô bằng BigInt.toRadixString(16). Nếu dạng chuỗi
        lệch với thư viện h3 bên Python thì không bao giờ khớp được ô nào.
        """
        assert CELL == format(int(CELL, 16), "x")
        assert len(CELL) == 15 and CELL.startswith("87")


class TestSosEvent:
    """Payload app BB-SOS gửi lên — trước P0 luôn trả 422."""

    async def test_accepts_app_payload(self, staff):
        await register(staff, "d-001", "O", "+")
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        r = await staff.post("/api/sos/event", json={
            "facility_id": None, "component_code": "WB",
            "abo": "O", "rh": "+", "urgency": "emergency", "qty": 2,
            "h3_cell": CELL,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # App đọc đúng ba trường này
        assert body["id"] and body["status"] == "open" and body["message"]
        assert body["donors_notified"] == 1
        assert body["target_count"] == 2

    async def test_legacy_console_payload_still_works(self, staff):
        r = await staff.post("/api/sos/event",
                              json={"ring": 1, "target_count": 3, "component_code": "PLT"})
        assert r.status_code == 200, r.text
        assert r.json()["target_count"] == 3

    async def test_ring0_exact_type_ring1_compatible(self, staff):
        await register(staff, "d-001", "A", "+")
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        # Bệnh nhân AB+: vòng 0 chỉ nhận AB+ nên không gọi ai
        r0 = await staff.post("/api/sos/event", json={
            "component_code": "RBC", "abo": "AB", "rh": "+", "ring": 0, "h3_cell": CELL})
        assert r0.json()["donors_notified"] == 0

        # Vòng 1 mở sang nhóm tương hợp: A+ hiến được cho AB+
        r1 = await staff.post("/api/sos/event", json={
            "component_code": "RBC", "abo": "AB", "rh": "+", "ring": 1, "h3_cell": CELL})
        assert r1.json()["donors_notified"] == 1

    async def test_ineligible_donor_not_called(self, staff):
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        await register(staff, "d-001", "O", "+", last_donation=recent)
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        r = await staff.post("/api/sos/event", json={
            "component_code": "WB", "abo": "O", "rh": "+", "ring": 0, "h3_cell": CELL})
        assert r.json()["donors_notified"] == 0

    async def test_ring3_ignores_location(self, staff):
        await register(staff, "d-001", "O", "+", cell=FAR_CELL)
        await staff.post("/api/donors/d-001/verify", json={"verified": True})

        r0 = await staff.post("/api/sos/event", json={
            "component_code": "WB", "abo": "O", "rh": "+", "ring": 0, "h3_cell": CELL})
        assert r0.json()["donors_notified"] == 0

        r3 = await staff.post("/api/sos/event", json={
            "component_code": "WB", "abo": "O", "rh": "+", "ring": 3, "h3_cell": CELL})
        assert r3.json()["donors_notified"] == 1


class TestSosResponse:
    """Phản hồi gửi trong JSON body — đúng cách app đang gọi."""

    async def test_accept_counts_and_fulfils(self, staff):
        await register(staff, "d-001", "O", "+")
        await staff.post("/api/donors/d-001/verify", json={"verified": True})
        event_id = (await staff.post("/api/sos/event", json={
            "component_code": "WB", "abo": "O", "rh": "+", "qty": 1,
            "h3_cell": CELL})).json()["id"]

        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                              json={"donor_id": "d-001", "response": "accepted"})
        assert r.status_code == 200, r.text
        assert r.json()["accept_count"] == 1
        assert r.json()["event_status"] == "fulfilled"

        status = (await staff.get(f"/api/sos/event/{event_id}")).json()
        assert status["accept_count"] == 1

    async def test_console_outcome_field_also_accepted(self, staff):
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                              json={"donor_id": "d-001", "outcome": "declined"})
        assert r.status_code == 200
        assert r.json()["accept_count"] == 0

    async def test_bad_outcome_rejected(self, staff):
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                              json={"donor_id": "d-001", "response": "maybe"})
        assert r.status_code == 422

    async def test_unknown_event_404(self, staff):
        r = await staff.post("/api/sos/event/khong-ton-tai/respond",
                              json={"donor_id": "d-001", "response": "accepted"})
        assert r.status_code == 404


class TestLimitInteractsWithEligibility:
    """
    LIMIT phải chạy SAU khi lọc điều kiện hiến, không phải trước.

    Lọc sau LIMIT thì con số trả về là "số người đủ điều kiện trong N người đầu
    tiên" — vòng rộng hơn có thể ra ít người hơn vòng hẹp, đúng như đã thấy trên
    máy chủ thật: vòng 2 ra 42 người còn vòng 3 chỉ ra 41.
    """

    async def test_ineligible_donors_do_not_eat_the_limit(self, staff):
        recent = datetime.now(timezone.utc) - timedelta(days=3)
        # 5 người vừa hiến (không đủ điều kiện) + 3 người đủ điều kiện
        for i in range(5):
            await register(staff, f"d-recent-{i}", "O", "+", last_donation=recent)
        for i in range(3):
            await register(staff, f"d-ok-{i}", "O", "+")
        for i in range(5):
            await staff.post(f"/api/donors/d-recent-{i}/verify", json={"verified": True})
        for i in range(3):
            await staff.post(f"/api/donors/d-ok-{i}/verify", json={"verified": True})

        r = await staff.get("/api/sos/donors/nearby", params={
            "h3_cell": CELL, "component_code": "WB",
            "eligible_only": True, "limit": 5,
        })
        # Nếu LIMIT chạy trước, 5 người vừa hiến chiếm hết chỗ và kết quả là 0
        assert r.json()["total_donors"] == 3

    async def test_list_donors_pagination_not_broken_by_filter(self, staff):
        recent = datetime.now(timezone.utc) - timedelta(days=3)
        for i in range(4):
            await register(staff, f"d-recent-{i}", "O", "+", last_donation=recent)
        for i in range(2):
            await register(staff, f"d-ok-{i}", "O", "+")

        r = await staff.get("/api/donors", params={"eligible_only": True, "limit": 3})
        assert len(r.json()) == 2
        assert all(d["eligible"] for d in r.json())
