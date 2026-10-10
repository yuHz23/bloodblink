"""
Fixture dùng chung cho test API.

Chạy trên SQLite trong bộ nhớ với đúng các bảng của luồng người hiến — bảng
`facility` dùng `geoalchemy2.Geometry` + `JSONB` nên không tạo được ở đây, vì
vậy test nào cần cơ sở y tế thì phải chạy trên Postgres.
"""

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import get_db
from app.main import app
from app.models.database import (
    Base, BloodUnit, Donor, SOSEvent, SOSResponse, SOSNotification, SOSReward, AppUser, AuditLog,
)
from app.services.auth import (
    hash_password, create_access_token,
    ROLE_DONOR, ROLE_FACILITY_STAFF, ROLE_ADMIN,
)

STAFF_USERNAME = "choray"
STAFF_PASSWORD = "choray@2026"

# Tài khoản test để `facility_id = None`: `/auth/login` tra tên cơ sở qua bảng
# `facility`, mà bảng đó không tạo được trên SQLite (Geometry + JSONB). Phần
# gắn cơ sở vào token được kiểm trên máy chủ Postgres thật, không kiểm ở đây.
STAFF_FACILITY = None

# `app_user.facility_id` trỏ tới bảng `facility` không được tạo ở đây;
# SQLite không cưỡng chế khoá ngoại nên vẫn chèn được.
TEST_TABLES = [
    Donor.__table__, SOSEvent.__table__, SOSResponse.__table__,
    SOSNotification.__table__, SOSReward.__table__, AppUser.__table__, AuditLog.__table__,
    BloodUnit.__table__,
]


@pytest_asyncio.fixture
async def session_factory():
    """
    Engine SQLite dùng chung cho cả client HTTP lẫn truy cập thẳng CSDL trong test.

    Test bộ lập lịch cần sửa `opened_at` để giả lập thời gian trôi, nên phải với
    tới đúng cơ sở dữ liệu mà API đang dùng.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TEST_TABLES)

    async with factory() as session:
        session.add(AppUser(
            id="user-choray",
            username=STAFF_USERNAME,
            password_hash=hash_password(STAFF_PASSWORD),
            role=ROLE_FACILITY_STAFF,
            facility_id=STAFF_FACILITY,
            full_name="Khoa Huyết học — Bệnh viện B",
            active=True,
        ))
        session.add(AppUser(
            id="user-khoa",
            username="khoa",
            password_hash=hash_password("khoa@2026"),
            role=ROLE_ADMIN,
            facility_id=None,
            full_name="Quản trị",
            active=False,          # tài khoản bị khoá, dùng cho test 403
        ))
        await session.commit()

    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    """Client chưa đăng nhập — dùng để kiểm tra endpoint có bị khoá không."""
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session(session_factory):
    """Phiên CSDL trỏ vào cùng dữ liệu mà `client` đang dùng."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def staff(client):
    """Client đã đăng nhập bằng tài khoản nhân viên cơ sở y tế."""
    r = await client.post("/api/auth/login",
                          json={"username": STAFF_USERNAME, "password": STAFF_PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return client


def donor_headers(donor_id: str) -> dict:
    """Header của chính người hiến — token do /donors/register cấp."""
    return {"Authorization": f"Bearer {create_access_token(donor_id, ROLE_DONOR)}"}


def admin_headers() -> dict:
    """Header quản trị cho test dữ liệu SOS chưa gắn cơ sở cụ thể."""
    return {"Authorization": f"Bearer {create_access_token('test-admin', ROLE_ADMIN)}"}
