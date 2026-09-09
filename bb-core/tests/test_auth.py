"""
BB-Core — Kiểm thử xác thực và phân quyền (P1).

Điều cần khoá lại: trước P1 mọi endpoint đều mở, ai biết địa chỉ máy chủ là
đọc được toàn bộ danh sách người hiến và tự xác minh chính mình.
"""

from datetime import timedelta

import h3
import jwt as pyjwt

from app.config import settings
from app.models.database import SOSNotification
from app.services.auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    ROLE_DONOR, ROLE_FACILITY_STAFF, ROLE_ADMIN,
)
from tests.conftest import STAFF_USERNAME, STAFF_PASSWORD, donor_headers

CELL = h3.latlng_to_cell(10.7626, 106.6602, settings.h3_resolution)


class TestPasswordHashing:

    def test_roundtrip(self):
        stored = hash_password("choray@2026")
        assert verify_password("choray@2026", stored)
        assert not verify_password("choray@2025", stored)

    def test_same_password_gives_different_hash(self):
        """Mỗi lần băm phải có muối riêng, nếu không lộ ra ai trùng mật khẩu."""
        assert hash_password("abc") != hash_password("abc")

    def test_malformed_hash_is_rejected_not_crashed(self):
        assert not verify_password("abc", "khong-phai-dinh-dang-hop-le")
        assert not verify_password("abc", "")


class TestToken:

    def test_claims_roundtrip(self):
        token = create_access_token("user-choray", ROLE_FACILITY_STAFF, "fac-bv-cho-ray")
        claims = decode_access_token(token)
        assert claims["sub"] == "user-choray"
        assert claims["role"] == ROLE_FACILITY_STAFF
        assert claims["facility_id"] == "fac-bv-cho-ray"

    def test_expired_token_rejected(self):
        token = create_access_token("user-choray", ROLE_ADMIN, expires_minutes=-1)
        try:
            decode_access_token(token)
            assert False, "token hết hạn phải bị từ chối"
        except pyjwt.ExpiredSignatureError:
            pass

    def test_token_signed_with_other_key_rejected(self):
        forged = pyjwt.encode(
            {"sub": "ke-gia-mao", "role": ROLE_ADMIN, "iss": "bb-core"},
            "khoa-khac", algorithm="HS256")
        try:
            decode_access_token(forged)
            assert False, "token ký bằng khoá khác phải bị từ chối"
        except pyjwt.PyJWTError:
            pass


class TestLogin:

    async def test_login_returns_token(self, client):
        r = await client.post("/api/auth/login",
                              json={"username": STAFF_USERNAME, "password": STAFF_PASSWORD})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["role"] == ROLE_FACILITY_STAFF
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == settings.jwt_expire_minutes * 60

    async def test_wrong_password_401(self, client):
        r = await client.post("/api/auth/login",
                              json={"username": STAFF_USERNAME, "password": "sai"})
        assert r.status_code == 401

    async def test_unknown_user_gives_same_message(self, client):
        """Không được để lộ tài khoản nào có thật qua thông điệp lỗi."""
        a = await client.post("/api/auth/login",
                              json={"username": STAFF_USERNAME, "password": "sai"})
        b = await client.post("/api/auth/login",
                              json={"username": "khong-ton-tai", "password": "sai"})
        assert a.status_code == b.status_code == 401
        assert a.json()["detail"] == b.json()["detail"]

    async def test_disabled_account_403(self, client):
        r = await client.post("/api/auth/login",
                              json={"username": "khoa", "password": "khoa@2026"})
        assert r.status_code == 403

    async def test_me_needs_token(self, client):
        assert (await client.get("/api/auth/me")).status_code == 401

    async def test_me_with_token(self, staff):
        r = await staff.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["role"] == ROLE_FACILITY_STAFF


class TestEndpointsAreLocked:
    """Không có token thì không đọc được gì về người hiến."""

    async def test_donor_endpoints_401_without_token(self, client):
        assert (await client.get("/api/donors")).status_code == 401
        assert (await client.get("/api/donors/bat-ky")).status_code == 401
        assert (await client.get("/api/sos/donors/nearby",
                                 params={"h3_cell": CELL})).status_code == 401
        assert (await client.post("/api/sos/event", json={"ring": 0})).status_code == 401

    async def test_register_stays_open(self, client):
        """Đăng ký là bước duy nhất chưa thể có token."""
        r = await client.post("/api/donors/register",
                              json={"id": "d-001", "abo": "O", "rh": "+"})
        assert r.status_code == 200
        assert r.json()["access_token"]

    async def test_health_stays_open(self, client):
        assert (await client.get("/api/health")).status_code == 200

    async def test_garbage_token_401(self, client):
        r = await client.get("/api/donors", headers={"Authorization": "Bearer khong-phai-jwt"})
        assert r.status_code == 401


class TestDonorScope:
    """Người hiến chỉ đụng được vào hồ sơ của chính mình."""

    async def test_donor_reads_own_profile(self, client):
        await client.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        r = await client.get("/api/donors/d-001", headers=donor_headers("d-001"))
        assert r.status_code == 200
        assert r.json()["id"] == "d-001"

    async def test_donor_cannot_read_someone_else(self, client):
        await client.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        await client.post("/api/donors/register", json={"id": "d-002", "abo": "A", "rh": "+"})
        r = await client.get("/api/donors/d-002", headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_cannot_move_someone_elses_geocell(self, client):
        await client.post("/api/donors/register", json={"id": "d-002", "abo": "A", "rh": "+"})
        r = await client.patch("/api/donors/d-002/geocell",
                               json={"h3_cell": CELL}, headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_cannot_verify_themselves(self, client):
        """Chốt chặn tin cậy của cả hệ thống — người hiến tự xác minh là hỏng."""
        await client.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        r = await client.post("/api/donors/d-001/verify",
                              json={"verified": True}, headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_cannot_list_all_donors(self, client):
        r = await client.get("/api/donors", headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_cannot_search_nearby(self, client):
        r = await client.get("/api/sos/donors/nearby",
                             params={"h3_cell": CELL}, headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_cannot_open_sos_event(self, client):
        r = await client.post("/api/sos/event", json={"ring": 0},
                              headers=donor_headers("d-001"))
        assert r.status_code == 403

    async def test_donor_answers_only_for_themselves(self, staff, db_session):
        await staff.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        event_id = (await staff.post("/api/sos/event", json={"ring": 0})).json()["id"]

        # d-001 phải thực sự được gọi thì mới trả lời được — trong hệ thống thật
        # app chỉ hiện lời kêu gọi lấy từ hộp thư, tức là từ bảng này.
        db_session.add(SOSNotification(
            id="notif-d001", sos_event_id=event_id, donor_id="d-001",
            ring=0, channel="store", status="sent",
        ))
        await db_session.commit()

        # Token của d-002 không trả lời thay d-001 được
        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                             json={"donor_id": "d-001", "response": "accepted"},
                             headers={**donor_headers("d-002")})
        assert r.status_code == 403

        r = await staff.post(f"/api/sos/event/{event_id}/respond",
                             json={"donor_id": "d-001", "response": "accepted"},
                             headers={**donor_headers("d-001")})
        assert r.status_code == 200


class TestStaffScope:

    async def test_staff_can_verify_and_list(self, staff):
        await staff.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        assert (await staff.post("/api/donors/d-001/verify",
                                 json={"verified": True})).status_code == 200
        assert (await staff.get("/api/donors")).status_code == 200

    async def test_register_token_is_donor_role_not_staff(self, client):
        """Token cấp lúc đăng ký phải là vai trò `donor`, không được leo thang."""
        r = await client.post("/api/donors/register", json={"id": "d-001", "abo": "O", "rh": "+"})
        claims = decode_access_token(r.json()["access_token"])
        assert claims["role"] == ROLE_DONOR
        assert claims["sub"] == "d-001"
