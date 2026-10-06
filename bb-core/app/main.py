"""
BB-Core — FastAPI application entry point.

Architecture per planning doc:
  BB-SOS (Flutter) ─┐
                      ├─ REST/JSON + WebSocket ── BB-Core (FastAPI + Postgres)
  BB-Console (React) ─┘                              ├─ Tồn kho lô FEFO
                                                      ├─ Ghép nguồn + giải thích
                                                      ├─ Leo thang cầu cứu
                                                      └─ Nhật ký ghi vết chuỗi băm
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.inventory import router as inventory_router
from app.api.matching import router as matching_router
from app.api.sos import router as sos_router
from app.api.routing import router as routing_router
from app.api.donors import router as donors_router
from app.api.auth import router as auth_router
from app.api.facilities import router as facilities_router
from app.api.audit import router as audit_router
from app.api.deps import require_staff
from app.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler

DEFAULT_JWT_SECRET = "bloodblink-dev-doi-khoa-nay-truoc-khi-trien-khai"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bộ lập lịch tự nâng vòng SOS sống cùng vòng đời ứng dụng."""
    # Khoá ký mặc định nằm trong mã nguồn công khai: ai cũng tự ký được token
    # vai trò admin. Chặn ngay lúc khởi động thay vì để lỡ mang lên máy chủ thật.
    if settings.jwt_secret == DEFAULT_JWT_SECRET and not settings.allow_default_jwt_secret:
        raise RuntimeError(
            "JWT_SECRET vẫn là giá trị mặc định trong mã nguồn — ai cũng giả mạo được "
            "token quản trị. Đặt JWT_SECRET trong bb-core/.env (sinh bằng "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`), "
            "hoặc đặt ALLOW_DEFAULT_JWT_SECRET=true nếu đang chạy thử trên máy cá nhân."
        )

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    lifespan=lifespan,
    title="BLOODBLINK Core API",
    description="Điều phối máu liên viện — matching engine, inventory, and chain-of-custody",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS — allow BB-Console (React) and BB-SOS (Flutter) in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://10.0.2.2:8000",   # Android emulator → host
        "https://bb-console-ten.vercel.app",  # BB-Console trên Vercel
    ],
    # Ba nhóm origin được phép:
    #
    # 1. localhost / 127.0.0.1 ở BẤT KỲ cổng nào. Trước đây chỗ này ghim cứng
    #    5173; Vite tự nhảy sang 5174 khi 5173 đã bị chiếm, và console báo
    #    "Failed to fetch" mà không nói lý do — mất khá nhiều thời gian mới lần
    #    ra là preflight bị chặn chứ không phải sai mật khẩu. Máy chủ này chỉ
    #    mở trong tailnet nên nới cổng ở localhost không mở rộng bề mặt tấn công.
    # 2. Máy trong tailnet (MagicDNS *.ts.net hoặc IP 100.x) — console mở từ
    #    điện thoại hay máy khác trong nhóm.
    # 3. Vercel preview/production deployments (*.vercel.app).
    allow_origin_regex=(
        r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
        r"|^https?://([a-z0-9-]+\.)*ts\.net(:\d+)?$"
        r"|^http://100\.\d+\.\d+\.\d+(:\d+)?$"
        r"|^https://[a-z0-9-]+\.vercel\.app$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount API routers ──────────────────────────────────────────

# Tồn kho / ghép nguồn / định tuyến là dữ liệu điều phối nội bộ — khoá cả router
# thay vì gắn phụ thuộc vào từng hàm, để thêm endpoint mới không quên bảo vệ.
app.include_router(inventory_router, prefix="/api/inventory", tags=["inventory"],
                   dependencies=[Depends(require_staff)])
app.include_router(matching_router, prefix="/api/matching", tags=["matching"],
                   dependencies=[Depends(require_staff)])
app.include_router(sos_router, prefix="/api/sos", tags=["sos"])
app.include_router(routing_router, prefix="/api/routing", tags=["routing"],
                   dependencies=[Depends(require_staff)])
app.include_router(donors_router, prefix="/api/donors", tags=["donors"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(facilities_router, prefix="/api/facilities", tags=["facilities"])
app.include_router(audit_router, prefix="/api/audit", tags=["audit"])


# ── Health check ──────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "bb-core",
        "version": "0.1.0",
    }


@app.get("/api/spec-summary")
async def spec_summary():
    """Return the two architectural constraints baked into the schema."""
    return {
        "constraints": [
            "NO patient medical data stored — only indexes and request codes",
            "donor stores H3 geocell (~1 km) with TTL, NOT raw coordinates",
        ],
        "temp_thresholds": {
            "note": "Two modes per component: STORAGE vs TRANSPORT (Art 20 TT 26/2013/TT-BYT)",
            "WB":   {"storage": "2-6°C", "transport": "1-10°C"},
            "RBC":  {"storage": "2-6°C", "transport": "1-10°C"},
            "PLT":  {"storage": "20-24°C", "transport": "20-24°C"},
            "FFP":  {"storage": "−25°C → 24mo, −18…−25°C → 12mo", "transport": "≤−18°C"},
        },
        "shelf_life": {
            "RBC": "42 days (Art 24.3 TT 26/2013/TT-BYT)",
            "PLT": "5 days (Art 30 TT 26/2013/TT-BYT)",
            "FFP": "12 months at −18…−25°C; 24 months at ≤−25°C (Art 33)",
        },
        "donation_interval": {
            "WB_RBC": "12 weeks (Art 6 TT 26/2013/TT-BYT)",
            "PLT_plasma": "2 weeks (Art 6 TT 26/2013/TT-BYT)",
        },
    }