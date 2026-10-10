"""
Khoá lại các lỗ hổng tìm ra ở đợt soát chất lượng 09/09/2026.

Mỗi test ở đây tương ứng một lỗi đã sửa. Chúng không kiểm "tính năng chạy đúng"
mà kiểm "cách hỏng cũ không quay lại được" — nên đừng nới lỏng khi thấy vướng.
"""

import pytest

from app.models.database import ABO, RhD, Donor, SOSEvent, SOSNotification, SOSResponse
from app.services import audit
from tests.conftest import donor_headers

pytestmark = pytest.mark.asyncio


async def _notify(db_session, event_id: str, donor_id: str, ring: int = 0) -> None:
    """Giả lập "người hiến này đã được gọi" — điều kiện để được trả lời."""
    db_session.add(SOSNotification(
        id=f"notif-{event_id[:8]}-{donor_id}",
        sos_event_id=event_id, donor_id=donor_id,
        ring=ring, channel="store", status="sent",
    ))
    await db_session.commit()


class TestRegisterKhongBiChiemHoSo:
    """Lỗi #1 — `/donors/register` từng cấp token cho bất kỳ mã nào gửi lên."""

    async def test_dang_ky_moi_tra_ve_bi_mat_thiet_bi(self, client):
        r = await client.post("/api/donors/register",
                              json={"id": "d-100", "abo": "O", "rh": "+"})
        assert r.status_code == 200, r.text
        assert r.json()["device_secret"], "lần đăng ký đầu phải cấp bí mật thiết bị"

    async def test_nguoi_la_khong_chiem_duoc_ho_so_da_co(self, client):
        first = await client.post("/api/donors/register",
                                  json={"id": "d-101", "abo": "O", "rh": "+"})
        assert first.status_code == 200

        # Đúng lệnh curl trong báo cáo soát: chỉ cần đoán mã là xong.
        attack = await client.post("/api/donors/register",
                                   json={"id": "d-101", "abo": "AB", "rh": "-"})
        assert attack.status_code == 403
        assert "access_token" not in attack.json()

    async def test_tan_cong_that_bai_khong_ghi_de_nhom_mau(self, client, db_session):
        await client.post("/api/donors/register",
                          json={"id": "d-102", "abo": "O", "rh": "+"})
        await client.post("/api/donors/register",
                          json={"id": "d-102", "abo": "AB", "rh": "-"})

        donor = await db_session.get(Donor, "d-102")
        assert (donor.abo.value, donor.rh.value) == ("O", "+")

    async def test_dung_bi_mat_thi_cap_nhat_duoc(self, client):
        first = await client.post("/api/donors/register",
                                  json={"id": "d-103", "abo": "O", "rh": "+"})
        secret = first.json()["device_secret"]

        again = await client.post("/api/donors/register",
                                  json={"id": "d-103", "abo": "A", "rh": "+",
                                        "device_secret": secret})
        assert again.status_code == 200, again.text
        assert again.json()["blood_type"] == "A+"
        # Bí mật chỉ cấp một lần; lần sau không trả lại nữa.
        assert again.json()["device_secret"] is None

    async def test_token_con_han_thay_duoc_bi_mat(self, client):
        """Đường phục hồi của app: token còn hạn thì đăng ký lại được."""
        await client.post("/api/donors/register",
                          json={"id": "d-104", "abo": "O", "rh": "+"})
        again = await client.post("/api/donors/register",
                                  json={"id": "d-104", "abo": "B", "rh": "+"},
                                  headers=donor_headers("d-104"))
        assert again.status_code == 200, again.text

    async def test_token_cua_nguoi_khac_khong_dung_duoc(self, client):
        await client.post("/api/donors/register",
                          json={"id": "d-105", "abo": "O", "rh": "+"})
        r = await client.post("/api/donors/register",
                              json={"id": "d-105", "abo": "AB", "rh": "-"},
                              headers=donor_headers("d-999"))
        assert r.status_code == 403


class TestKhongDemTrungLoiNhan:
    """Lỗi #2 — gửi lại "Nhận lời" từng cộng dồn `accept_count`."""

    async def test_gui_lai_khong_lam_tang_so_dem(self, staff):
        # Xác minh người hiến để ca SOS mở ra gọi được ngay ở vòng 0. Nếu để
        # người chưa xác minh, việc mở ca tự leo thang hết bốn vòng mà chẳng
        # gọi được ai và ca bị đóng luôn thành "expired" — mất tiền đề
        # "ca còn mở" mà test này cần kiểm tra.
        await staff.post("/api/donors/register", json={"id": "d-200", "abo": "O", "rh": "+"})
        await staff.post("/api/donors/d-200/verify", json={"verified": True})
        event_id = (await staff.post("/api/sos/event",
                                     json={"ring": 0, "target_count": 2})).json()["id"]

        body = {"donor_id": "d-200", "response": "accepted"}
        h = donor_headers("d-200")
        first = await staff.post(f"/api/sos/event/{event_id}/respond", json=body, headers=h)
        second = await staff.post(f"/api/sos/event/{event_id}/respond", json=body, headers=h)

        assert first.status_code == 200 and second.status_code == 200
        assert second.json()["accept_count"] == 1
        # Chỗ chết người: đếm thành 2 thì ca cần 2 người bị coi là đủ và bộ lập
        # lịch (chỉ quét "open") thôi gọi thêm ai.
        assert second.json()["event_status"] == "open"

    async def test_khong_de_lai_hai_dong_phan_hoi(self, staff, db_session):
        await staff.post("/api/donors/register", json={"id": "d-201", "abo": "O", "rh": "+"})
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        await _notify(db_session, event_id, "d-201")

        h = donor_headers("d-201")
        for _ in range(3):
            await staff.post(f"/api/sos/event/{event_id}/respond",
                             json={"donor_id": "d-201", "response": "accepted"}, headers=h)

        from sqlalchemy import select
        rows = (await db_session.execute(
            select(SOSResponse).where(SOSResponse.sos_event_id == event_id)
        )).scalars().all()
        assert len(rows) == 1

    async def test_doi_y_thi_xoa_so_dien_thoai(self, staff, db_session):
        await staff.post("/api/donors/register", json={"id": "d-202", "abo": "O", "rh": "+"})
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        await _notify(db_session, event_id, "d-202")

        h = donor_headers("d-202")
        await staff.post(f"/api/sos/event/{event_id}/respond", headers=h,
                         json={"donor_id": "d-202", "response": "accepted",
                               "contact_phone": "0900000000"})
        r = await staff.post(f"/api/sos/event/{event_id}/respond", headers=h,
                             json={"donor_id": "d-202", "response": "declined"})

        assert r.json()["accept_count"] == 0
        from sqlalchemy import select
        row = (await db_session.execute(
            select(SOSResponse).where(SOSResponse.sos_event_id == event_id)
        )).scalars().one()
        assert row.contact_phone is None, "từ chối rồi thì không giữ số điện thoại"

    async def test_khong_tra_loi_cho_ca_minh_khong_duoc_goi(self, staff):
        await staff.post("/api/donors/register", json={"id": "d-203", "abo": "O", "rh": "+"})
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]

        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                             json={"donor_id": "d-203", "response": "accepted"},
                             headers=donor_headers("d-203"))
        assert r.status_code == 403


class TestNhatKyKhongLamHongNghiepVu:
    """Lỗi #7 — `audit.record` hỏng từng kéo sập giao dịch của bên gọi."""

    async def test_ghi_nhat_ky_hong_van_commit_duoc_viec_chinh(self, db_session):
        db_session.add(Donor(id="d-300", abo=ABO.O, rh=RhD.POS, verified=False))
        await db_session.commit()

        # `actor` là None → cột NOT NULL → flush hỏng. Đúng kiểu hỏng mà module
        # nói là phải nuốt được.
        entry = await audit.record(db_session, None, audit.DONOR_VERIFY, {"x": 1})
        assert entry is None

        donor = await db_session.get(Donor, "d-300")
        donor.verified = True
        await db_session.commit()          # trước đây nổ PendingRollbackError

        await db_session.refresh(donor)
        assert donor.verified is True

    async def test_chuoi_bam_van_lien_sau_lan_ghi_hong(self, db_session):
        a = await audit.record(db_session, "u-1", audit.LOGIN, {})
        await audit.record(db_session, None, audit.LOGIN, {})     # hỏng, bị bỏ
        b = await audit.record(db_session, "u-2", audit.LOGIN, {})
        await db_session.commit()

        assert b.prev_hash == a.hash
        assert (await audit.verify_chain(db_session))["ok"] is True


class TestTimQuanhKhopVoiGoiThat:
    """Lỗi #10 — con số trên console từng lệch với số người thật sự được gọi."""

    async def test_o_luoi_het_han_khong_duoc_dem(self, staff, db_session):
        import h3
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select

        cell = h3.latlng_to_cell(10.7546, 106.6633, 7)
        now = datetime.now(timezone.utc)

        db_session.add_all([
            # Còn hạn → phải thấy
            Donor(id="d-400", abo=ABO.O, rh=RhD.POS, verified=True,
                  geocell_h3=cell, geocell_ttl=now + timedelta(hours=4)),
            # TTL NULL → KHÔNG được thấy: `select_donors` sẽ không gọi người này,
            # nên đếm vào là nhân viên nhìn một con số không có thật.
            Donor(id="d-401", abo=ABO.O, rh=RhD.POS, verified=True,
                  geocell_h3=cell, geocell_ttl=None),
            # Hết hạn → không thấy
            Donor(id="d-402", abo=ABO.O, rh=RhD.POS, verified=True,
                  geocell_h3=cell, geocell_ttl=now - timedelta(hours=1)),
        ])
        await db_session.commit()

        r = await staff.get("/api/sos/donors/nearby",
                            params={"h3_cell": cell, "ring": 0, "abo": "O", "rh": "+"})
        assert r.status_code == 200, r.text
        ids = {row["donor_id"] for row in r.json()["donors"]}
        assert "d-400" in ids
        assert "d-401" not in ids and "d-402" not in ids

    async def test_tim_quanh_va_goi_that_ra_cung_mot_tap(self, staff, db_session):
        """Vòng 3 là chỗ hai bên từng lệch theo chiều ngược lại."""
        import h3
        from datetime import datetime, timedelta, timezone
        from app.services.sos_dispatch import select_donors

        cell = h3.latlng_to_cell(10.7546, 106.6633, 7)
        now = datetime.now(timezone.utc)
        db_session.add_all([
            Donor(id="d-410", abo=ABO.O, rh=RhD.POS, verified=True,
                  geocell_h3=cell, geocell_ttl=now + timedelta(hours=4)),
            Donor(id="d-411", abo=ABO.O, rh=RhD.POS, verified=True,
                  geocell_h3=cell, geocell_ttl=None),
        ])
        await db_session.commit()

        for ring in (0, 3):
            r = await staff.get("/api/sos/donors/nearby",
                                params={"h3_cell": cell, "ring": ring, "abo": "O", "rh": "+"})
            nearby = {row["donor_id"] for row in r.json()["donors"]}
            called = {d.id for d in await select_donors(
                db_session, cell=cell, ring=ring, abo="O", rh="+", component="WB")}
            assert nearby == called, f"vòng {ring}: console thấy {nearby}, thật sự gọi {called}"


class TestSuKienSOSKhongDoDuoc:
    """Lỗi #11 — mọi tài khoản đã đăng nhập từng đọc được mọi sự kiện."""

    async def test_nhan_vien_doc_duoc(self, staff):
        eid = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        assert (await staff.get(f"/api/sos/event/{eid}")).status_code == 200

    async def test_nguoi_hien_khong_duoc_goi_thi_khong_doc_duoc(self, staff):
        eid = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        r = await staff.get(f"/api/sos/event/{eid}", headers=donor_headers("d-500"))
        # 404 chứ không 403: 403 là xác nhận mã sự kiện có thật.
        assert r.status_code == 404

    async def test_nguoi_hien_duoc_goi_thi_doc_duoc(self, staff, db_session):
        await staff.post("/api/donors/register", json={"id": "d-501", "abo": "O", "rh": "+"})
        eid = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]
        await _notify(db_session, eid, "d-501")

        r = await staff.get(f"/api/sos/event/{eid}", headers=donor_headers("d-501"))
        assert r.status_code == 200, r.text
