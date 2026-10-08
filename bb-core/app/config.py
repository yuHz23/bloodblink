"""BB-Core configuration — pydantic-settings, reads .env"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Database ──
    database_url: str = "postgresql+asyncpg://bloodblink:bloodblink@localhost:5432/bloodblink"
    database_ssl: bool = False
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "bloodblink"
    postgres_user: str = "bloodblink"
    postgres_password: str = "bloodblink"

    # ── Simulation ──
    sim_seed: int = 42
    sim_days: int = 90
    sim_start_date: str = "2025-07-01"
    osrm_url: str = "http://localhost:5000"

    # ── Safety thresholds (TT 26/2013/TT-BYT) ──
    # Two modes per component: STORAGE vs TRANSPORT (Article 20)
    temp_thresholds: dict = {
        # component_code: {mode: (min_c, max_c)}
        "WB":   {"storage": (2, 6), "transport": (1, 10)},       # Whole blood
        "RBC":  {"storage": (2, 6), "transport": (1, 10)},       # Red blood cells
        "PLT":  {"storage": (20, 24), "transport": (20, 24)},    # Platelets
        "FFP":  {"storage": (-25, -18), "transport": (-25, -18)},# Fresh frozen plasma (≤−25: 24mo)
        "CRYO": {"storage": (-25, -18), "transport": (-25, -18)},# Cryoprecipitate
    }

    # ── Shelf life (days) per TT 26/2013/TT-BYT ──
    shelf_life_days: dict = {
        "WB":   42,    # Art 24.3 — closed system, max 42 days from collection
        "RBC":  42,    # Art 24.3
        "PLT":  5,     # Art 30 — 20-24°C with agitation
        "FFP":  None,   # Art 33 — months, not days (12mo at −18…−25°C, 24mo at ≤−25°C)
        "CRYO": None,
    }

    # ── Donation interval (weeks) per Art 6 ──
    donation_interval_weeks: dict = {
        "WB":  12,
        "RBC": 12,
        "PLT": 2,
        "CRYO": 2,
    }

    # ── Blood group distribution — Vietnamese population (Viện HH-TMTW) ──
    abo_distribution: dict = {"O": 0.45, "B": 0.30, "A": 0.20, "AB": 0.05}
    rh_positive_ratio: float = 0.999  # ~0.1% Rh(D) negative

    # ── BB-SOS escalation windows (minutes) ──
    sos_rings: list[int] = [0, 10, 25, 45]  # ring 0 (immediate) → ring 3

    # ── H3 resolution for geocell ──
    # Res 7 ≈ 1.22 km cạnh ô — đúng mốc "~1 km" trong thiết kế và khớp với
    # H3Config.resolution của app BB-SOS. Res 9 (~174 m) khiến ô app sinh ra
    # không bao giờ khớp ô server tìm.
    h3_resolution: int = 7

    # TTL mặc định của ô lưới người hiến (giờ) — hết hạn thì không còn được tìm thấy
    geocell_ttl_hours: int = 4

    # ── Đẩy thông báo & leo thang tự động ──
    # "store": ghi lời kêu gọi vào bảng sos_notification để app tự hỏi hộp thư.
    # "fcm":   gửi qua Firebase Cloud Messaging, cần fcm_credentials_path.
    push_provider: str = "store"
    fcm_credentials_path: str = ""       # đường dẫn service-account JSON
    fcm_project_id: str = ""

    # Bộ lập lịch tự nâng vòng theo mốc sos_rings (T+0/10/25/45 phút)
    sos_auto_escalate: bool = True
    sos_scheduler_interval_seconds: int = 30
    # Sự kiện quá hạn này mà chưa đủ người thì đóng lại, thôi leo thang
    sos_event_ttl_minutes: int = 180

    # ── Xác thực ──
    # ĐỔI trước khi triển khai thật: token ký bằng khoá này, lộ khoá là giả mạo
    # được mọi vai trò. Đặt qua biến môi trường JWT_SECRET hoặc bb-core/.env.
    jwt_secret: str = "bloodblink-dev-doi-khoa-nay-truoc-khi-trien-khai"
    jwt_expire_minutes: int = 12 * 60      # nhân viên trực một ca

    # Máy chủ TỪ CHỐI khởi động nếu jwt_secret còn là giá trị mặc định, trừ khi
    # bật cờ này. Đặt True chỉ khi chạy test hoặc nghịch trên máy cá nhân.
    allow_default_jwt_secret: bool = False

    # ── Matching engine ──
    safety_margin_hours: float = 2.0   # buffer before expiry
    default_eta_seconds: int = 5400     # 90 min fallback ETA


settings = Settings()
