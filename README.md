# BLOODBLINK — Điều phối máu liên viện

> Nền tảng điều phối máu liên viện + huy động người hiến + giám sát chuỗi lạnh  
> Dự thi **GenD Arena 2026** — Lĩnh vực Y tế và sức khỏe

## 🏗️ Kiến trúc

```
BB-SOS (Flutter)  ──┐
                      ├── REST/JSON ── BB-Core (FastAPI + PostgreSQL)
BB-Console (React) ──┘                     ├── Matching engine (ABO/RhD)
                      │                     ├── FEFO inventory
                      │                     ├── Routing + ETA (OSRM)
                      │                     └── SOS 4-ring escalation
BB-Box (ESP32-S3) ────┘── REST ────────── BB-Core API
```

## 📦 Modules

| Module | Công nghệ | Mô tả | Tests |
|--------|-----------|-------|-------|
| `bb-core/` | Python 3.12 + FastAPI + SQLAlchemy | Backend API, matching engine, ABO/RhD, SOS, ghi vết, FHIR R5 | 226 |
| `bb-console/` | React + Vite + TypeScript | Dashboard cơ sở y tế + bản đồ điều phối | ✓ |
| `bb-sos/` | Flutter + Riverpod + Hive | App người hiến máu | 38 |
| `bb-box/` | ESP32-S3 + FreeRTOS + Arduino | Cảm biến nhiệt độ chuỗi lạnh | 46 |
| `bb-sim/` | Python | Mô phỏng sự kiện rời rạc | ✓ |

**Tổng: 310 tests pass** (226 + 38 + 46; phần C++ của bb-box cần PlatformIO)

## 🔑 Tính năng chính

### 1. Matching Engine liên viện
- Tìm nguồn máu ABO/RhD tương hợp trên **tất cả** cơ sở đã opt-in
- 5 yếu tố xếp hạng: FEFO, ETA, nhóm máu, tồn kho nguồn, rủi ro O-
- **Ràng buộc RhD**: KHÔNG hạ chuẩn Rh(+) cho nữ 18-45 tuổi

### 2. Hai chế độ ngưỡng nhiệt (Điều 20 TT 26/2013/TT-BYT)
| Thành phần | Bảo quản | Vận chuyển |
|-----------|----------|------------|
| WB/RBC | 2–6°C | 1–10°C |
| Tiểu cầu | 20–24°C | 20–24°C |
| Huyết tương | −25 → −18°C | −18 → −10°C |

> ⚠️ **8°C cho RBC**: NGUY HIỂM khi bảo quản, BÌNH THƯỜNG khi vận chuyển.

### 3. SOS 4-ring huy động người hiến
- Ring 1: T+0 phút, 1 km, ~30% phản hồi
- Ring 2: T+10 phút, 5 km, ~20% thêm
- Ring 3: T+25 phút, 10 km, ~15% thêm
- Ring 4: T+45 phút, 20 km, ~10% thêm
- **Máy chủ tự nâng vòng** theo mốc T+0/10/25/45 (`services/scheduler.py`, quét mỗi 30 giây);
  leo thang trên chính sự kiện đó nên mỗi người hiến chỉ bị gọi **một lần** cho cả lời kêu gọi
- Lọc theo Điều 6: khoảng cách hiến (WB/RBC 12 tuần, PLT/FFP 2 tuần) — **phán quyết ở máy chủ**
- Quyền riêng tư: **H3 geocell res 7 (~1.2 km) với TTL 4 giờ**, không lưu GPS thô
- Vòng 0 chỉ gọi người **cùng nhóm máu**; từ vòng 1 mới mở sang nhóm **tương hợp**

#### Xác thực và phân quyền
Từ P1, **mọi endpoint dưới `/api` đều cần Bearer token**, trừ bốn cái:
`/api/health`, `/api/spec-summary`, `/api/auth/login`, `/api/donors/register`.

| Vai trò | Nhận token bằng | Làm được gì |
|---|---|---|
| `facility_staff` | `POST /api/auth/login` | Tra người hiến, xác minh, mở SOS, tồn kho, ghép nguồn |
| `admin` | `POST /api/auth/login` | Như trên, không gắn cơ sở cụ thể |
| `donor` | `POST /api/donors/register` trả kèm token | CHỈ hồ sơ của chính mình + trả lời SOS của chính mình |

Người hiến **không** tự xác minh, không xem được danh sách người hiến, không mở
được SOS — có test khoá từng đường một trong `tests/test_auth.py`.

Tài khoản dữ liệu mẫu (đổi ngay khi chạy thật): `admin` / `bloodblink@2026`,
`choray` / `choray@2026`, `tmhh` / `tmhh@2026`, `ungbuou`, `nhidong`, `phamngocthach`.

#### Bảo mật & ghi vết (P4)
- **Khoá ký**: máy chủ **từ chối khởi động** nếu `JWT_SECRET` còn là giá trị mặc định
  trong mã nguồn. Sinh khoá: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  rồi đặt vào `bb-core/.env`. Đổi khoá là mọi phiên đang đăng nhập bị vô hiệu.
- **Nhật ký chuỗi băm** (`services/audit.py`): đăng nhập (kể cả lần hỏng), xác minh
  người hiến, tra danh sách, mở/leo thang SOS, phản hồi, và mỗi lần xem danh tính đều
  ghi một dòng băm cả dòng trước nó. `GET /api/audit/verify` (chỉ quản trị) chỉ ra
  dòng đầu tiên bị sửa nếu chuỗi gãy.
- **Danh tính chỉ lộ khi nhận lời**: máy chủ không có sẵn số điện thoại của ai. Người
  hiến tự nhập số lúc bấm "Tôi có thể hiến"; từ chối thì không lưu gì. Chỉ cơ sở phát
  lời kêu gọi (hoặc quản trị) đọc được `GET /api/sos/event/{id}/responses`.

#### Đẩy thông báo
Dự án **chưa có Firebase** (không có `google-services.json`, gradle chưa gắn plugin).
`services/push.py` theo đúng khuôn `RoutingProvider`: một giao diện, hai hiện thực.

| Kênh | Cách hoạt động | Đánh đổi |
|---|---|---|
| `store` (mặc định) | Ghi vào bảng `sos_notification`; app BB-SOS hỏi hộp thư mỗi 45 giây rồi tự dựng thông báo trên máy | Chạy ngay, không phụ thuộc dịch vụ ngoài — nhưng chỉ nhận được khi app còn sống |
| `fcm` | Firebase Cloud Messaging HTTP v1 | Nhận cả khi app đã tắt — cần `fcm_credentials_path` + `fcm_project_id` |

Bật FCM: đặt `PUSH_PROVIDER=fcm` và hai biến trên trong `bb-core/.env`, rồi đẩy token
thiết bị lên `PUT /api/donors/{id}/push-token`. Bảng `sos_notification` vẫn được ghi ở
cả hai kênh — nó là nhật ký ghi vết "ai đã được gọi", không chỉ là hộp thư.

#### API người hiến (`/api/donors`)
Đường đi của hồ sơ từ app BB-SOS vào hệ thống — không có nhóm endpoint này thì
bảng `donor` chỉ có dữ liệu seed và không cơ sở nào tìm ra người cùng nhóm máu:

| Method | Path | Việc |
|---|---|---|
| `POST` | `/api/donors/register` | Đăng ký / cập nhật hồ sơ (upsert theo id app sinh) |
| `GET` | `/api/donors/{id}` | Đọc hồ sơ + điều kiện hiến theo chế phẩm |
| `PATCH` | `/api/donors/{id}/geocell` | Làm mới ô lưới H3 + TTL |
| `DELETE` | `/api/donors/{id}/geocell` | Rút lại đồng ý chia sẻ vị trí |
| `POST` | `/api/donors/{id}/donation` | Ghi nhận một lần hiến (mốc Điều 6) |
| `POST` | `/api/donors/{id}/verify` | Cơ sở y tế xác minh người hiến |

Nhóm endpoint cho bản đồ và cho việc nối ghép nguồn với SOS:

| Method | Endpoint | Mục đích |
|--------|----------|----------|
| `GET` | `/api/inventory/by-facility` | Tồn kho theo **cơ sở × nhóm máu**, chỉ đếm còn hạn |
| `GET` | `/api/sos/events?status=open` | Các lời kêu gọi đang mở — chấm nhu cầu lên bản đồ |
| `GET` | `/api/sos/donors/density` | Mật độ người hiến theo ô lưới H3, có k-ẩn danh. **Không trả mã người hiến nào** |
| `GET` | `/api/donors?abo=O&rh=%2B` | Tra người cùng nhóm máu toàn thành phố |
| `PUT` | `/api/donors/{id}/push-token` | Đăng ký thiết bị nhận thông báo đẩy |
| `GET` | `/api/donors/{id}/sos-inbox` | Hộp thư lời kêu gọi đang chờ trả lời |
| `POST` | `/api/sos/event/{id}/escalate` | Nâng vòng sớm, không đợi mốc thời gian |
| `GET` | `/api/sos/event/{id}/notifications` | Nhật ký: ai đã được gọi, vòng nào, kênh gì |
| `GET` | `/api/sos/event/{id}/responses` | Người đã nhận lời + liên hệ họ tự cung cấp |
| `GET` | `/api/audit`, `/api/audit/verify` | Nhật ký ghi vết và kiểm tra chuỗi băm (quản trị) |

Cơ sở y tế tra cứu qua BB-Console ở mục **Tìm người hiến**: chọn cơ sở → nhóm máu →
chế phẩm → vòng, kết quả là danh sách ẩn danh kèm nút xác minh và nút mở SOS.

Máy chủ **không nhận** họ tên và toạ độ thô: app tự quy toạ độ thành ô lưới H3
trên máy rồi chỉ gửi chỉ số ô kèm TTL.

### 4. Tìm kho trước, huy động người hiến sau

Thứ tự này là **kết luận về mặt thời gian**, không phải lựa chọn giao diện.

Một đơn vị máu vừa lấy từ người hiến phải qua sàng lọc bắt buộc (HIV, HBV, HCV,
giang mai — Điều 14–15 TT 26/2013), tách chế phẩm, định nhóm, rồi phản ứng hoà
hợp với người bệnh: nhanh nhất cũng vài giờ. Máu trong kho viện khác **đã qua
hết các bước đó** — chỉ còn hoà hợp và vận chuyển, mà ETA nội thành đo được là
5,8 phút.

Nên với mức khẩn *"Cấp cứu — cần trong 2 giờ"* của chính hệ thống, **huy động
người hiến không kịp cứu chính ca đó**. Giao diện nói thẳng điều này thay vì để
người điều phối ngồi chờ một thứ không tới.

Huy động người hiến có nghĩa ở bốn chỗ, và `app/services/sos_advice.py` phân
biệt đúng bốn chỗ ấy sau mỗi lần tìm nguồn:

| Tình huống | Kết luận | Đề nghị |
|---|---|---|
| Không có đơn vị tương hợp nào | **Bắt buộc** | Giữ mức khẩn của ca, vòng 0 |
| Kho chỉ đáp ứng một phần | **Bắt buộc** | Chỉ gọi đúng phần thiếu |
| Rút xong kho nguồn tụt sát ngưỡng an toàn | **Khuyến nghị bù** | Ép `routine`, vòng 2 |
| Đủ, kho vẫn dày, nhóm phổ biến | Không cần | — |

Nhánh thứ ba đảo ngược cách hiểu thông thường: **điều chuyển thành công vẫn nên
mở SOS**. Rút một đơn vị O⁻ khỏi kho thành phố là làm mỏng lớp phòng thủ cho ca
kế tiếp, và không ai đang cuống mà nhớ ra điều đó. Lời kêu gọi để bù kho bị ép
về mức `routine` — gắn nhãn cấp cứu cho việc không cấp cứu sẽ làm nhãn đó mất
thiêng với người hiến.

### 5. Bản đồ điều phối

Ba lớp trên một khung nhìn (`bb-console/src/pages/MapView.tsx`, Leaflet):

- **Bệnh viện** — chấm to nhỏ theo số đơn vị, tô đỏ→xanh theo mức tồn của nhóm
  máu đang lọc. Chỉ đếm đơn vị **còn hạn**.
- **Ca đang cần** — ghim gom theo cơ sở. Một bệnh viện mở nhiều ca thì hiện
  `"3 ca"`; rải ghim ra quanh cho đỡ chồng là đặt ca vào chỗ nó không nằm ở đó.
- **Người hiến** — ô lưới H3 tô đậm theo mật độ, **không bao giờ là chấm cá
  nhân**. Hệ thống chỉ lưu ô lưới ~1,2 km chứ không lưu toạ độ, nên bản đồ này
  không thể chỉ ra ai đang ở đâu — kể cả khi muốn.

`GET /api/sos/donors/density` còn áp **k-ẩn danh**: ô nào có ít hơn `min_donors`
(mặc định 3) người thì bỏ hẳn khỏi kết quả. Một ô chỉ có đúng một người, đặt
cạnh một tấm ảnh hay một lời kể, là đủ để lần ra người đó. Bản đồ hiển thị số ô
bị ẩn thay vì giấu luôn việc mình đang giấu.

### 6. Bệnh viện gần bạn (app)

Người hiến nhận lời xong thì câu hỏi kế tiếp luôn là *"đi đâu, xa không"*.
App tải toạ độ bệnh viện về — dữ liệu công khai — rồi **tính khoảng cách ngay
trên máy**; vị trí thô không rời khỏi thiết bị. Nút chỉ đường mở lược đồ `geo:`
để Android tự hỏi chọn ứng dụng bản đồ, không ép cài Google Maps.

Không cấp quyền vị trí thì **vẫn hiện đủ danh sách**, chỉ thiếu khoảng cách —
thiếu GPS không phải lý do để chặn cả màn hình.

### 7. Routing + ETA thật
- RoutingProvider interface: StraightLine (haversine) + OSRM
- ETA cache theo cơ sở, emergency mode (40 km/h)
- 20 cặp ETA giữa 8 bệnh viện TP.HCM

## 📊 Kết quả mô phỏng (90 ngày, 8 BV TP.HCM)

| Chỉ số | Baseline | BLOODBLINK | Thay đổi |
|--------|----------|------------|----------|
| Tỷ lệ đáp ứng | 97.7% | 99.8% | **+2.1pp** |
| Khớp chính xác | 94.2% | 99.0% | **+4.8pp** |
| Thời gian TB | 5 giờ | 7 phút | **−97.6%** |
| Đơn vị hủy | 1,095 | 695 | **−36.5%** |

## 🚀 Chạy nhanh

### Máy chủ tạm trên laptop (P3)
```powershell
# Postgres+PostGIS trong WSL Ubuntu + bb-core trên Windows, bind 0.0.0.0:8000
powershell -ExecutionPolicy Bypass -File scripts\start-server.ps1        # thêm -Seed để nạp lại dữ liệu
```
Điện thoại trong tailnet gọi vào `http://laptop-rrqk96mj.tail85e1ba.ts.net:8000/api`
(đây cũng là URL mặc định biên dịch sẵn trong APK).

Hai bẫy đã ghim sẵn trong script, đừng gỡ:
- Giữ một tiến trình sống trong WSL, nếu không máy ảo tắt và cầu chuyển cổng localhost
  sập theo — từ Windows nhìn vào là `WinError 1225` dù Postgres vẫn chạy bên trong.
- Dùng `127.0.0.1`, không dùng `localhost`: localhost phân giải ra ::1 trước mà cầu
  chuyển cổng của WSL2 chỉ chuyển IPv4.

### Phiên bản Python

**Dùng Python 3.12 hoặc 3.13. KHÔNG dùng 3.14.**

Các bản ghim trong `requirements.txt` thuộc thế hệ trước Python 3.14, nên trên
3.14 thì `asyncpg`, `h3`, `pydantic-core`, `numpy`, `shapely` **đều không có
wheel** — pip sẽ cố biên dịch từ mã nguồn, cần MSVC và Rust. Trên máy không có
Visual Studio Build Tools thì hỏng hoàn toàn, và thông báo lỗi không hề nói rằng
nguyên nhân là phiên bản Python.

Đã đo trên máy sạch (Windows 10, Python 3.14.2): không cài được gói nào.
Cùng máy đó với Python 3.12.10: cài trọn vẹn.

```bash
py -3.12 -m venv .venv      # Windows
python3.12 -m venv .venv    # Linux/macOS
```

### BB-Core (backend)
```bash
cd bb-core
pip install -r requirements.txt
uvicorn app.main:app --reload
# API docs: http://localhost:8000/api/docs
```

### BB-Console (dashboard)
```bash
cd bb-console
npm install && npm run dev
# Dashboard: http://localhost:5173
```

### BB-SOS (mobile)
```bash
cd bb-sos
flutter pub get
flutter run

# Trỏ vào máy chủ khác lúc build (mặc định: laptop chạy bb-core qua Tailscale)
flutter build apk --release --dart-define=API_URL=http://<host>:8000/api
```
Đổi máy chủ lúc chạy: **Cài đặt → API URL → Kiểm tra kết nối**.

### BB-Box (firmware)
```bash
cd bb-box
pio run -e esp32-s3        # Build firmware
pio test -e native          # Run threshold tests (requires gcc)
python test/test_thresholds.py  # Python threshold tests (no gcc needed)
```

### BB-Sim (simulation)
```bash
cd bb-sim
python simulation.py --days 30 --verbose
python simulation.py --days 90    # Extended run
```

### Demo script (5 phút)
```bash
python demo_script.py              # Requires BB-Core running
```

## 📋 Số liệu đã kiểm chứng

- **1.748.935 đơn vị máu** tiếp nhận năm 2025 (cả nước, đạt 94% chỉ tiêu)
- **146.329 đơn vị** tại BV TMHH TP.HCM 6 tháng đầu 2025
- **~1.74% dân số** hiến máu (WHO chỉ nêu ngưỡng 1%)
- **O~45%, B~30%, A~20%, AB~5%** — phân bố nhóm máu người Việt (Viện HH-TMTW)
- **Rh(D)− chỉ ~0.1%** — tài nguyên khan hiếm
- TT 26/2013/TT-BYT: Điều 4 (tiêu chuẩn hiến), Điều 6 (khoảng cách), Điều 20 (vận chuyển), Điều 24/30/33 (thời hạn lưu trữ)
- TT 13/2025/TT-BYT: BAĐT hiệu lực 21/7/2025

## 🏆 Giải thưởng quy định

- **Điều 20 TT 26/2013/TT-BYT**: Hai chế độ ngưỡng (bảo quản vs vận chuyển)
- **Điều 6 TT 26**: Khoảng cách hiến máu theo loại (WB/RBC 12 tuần, PLT/FFP 2 tuần)
- **Điều 4 TT 26**: Tiêu chuẩn người hiến (18-60 tuổi, cân nặng, Hb)
- **TT 13/2025/TT-BYT**: BAĐT cho cơ sở KCB

## 📁 Cấu trúc thư mục

```
bloodblink/
├── bb-core/           # FastAPI backend
│   ├── app/
│   │   ├── api/       # REST endpoints (inventory, matching, sos, routing)
│   │   ├── models/     # SQLAlchemy models + seed data
│   │   ├── services/   # compatibility, matching, routing, sos_dispatch,
│   │   │                #   sos_advice (nối ghép nguồn ↔ SOS), audit, auth
│   │   └── config.py
│   ├── tests/          # 226 tests
│   └── seed/           # Database seed script
├── bb-console/         # React dashboard
│   ├── src/
│   │   ├── pages/      # Dashboard, Inventory, Matching, Donors, SOS,
│   │   │                #   MapView, Routing, Reports
│   │   └── lib/api.ts  # API client
│   └── package.json
├── bb-sos/             # Flutter mobile app
│   ├── lib/
│   │   ├── models/     # DonorProfile, DonationType, H3Config, SosRing
│   │   ├── screens/    # Home, SOS active, Profile, History, Settings,
│   │   │                #   NearbyFacilities
│   │   ├── services/   # API service (offline-first)
│   │   └── widgets/    # BloodTypeBadge, EligibilityCard, RingProgress
│   └── test/           # 38 tests
├── bb-box/             # ESP32-S3 firmware
│   ├── include/        # config.h, shipment_reading.h
│   ├── src/main.cpp    # FreeRTOS tasks (sensor, upload, LED)
│   ├── test/           # 46 threshold tests
│   └── platformio.ini
├── bb-sim/             # Discrete event simulation
│   └── simulation.py   # 90-day baseline vs BLOODBLINK
├── demo_script.py      # 5-minute demo walkthrough
└── docker-compose.osrm.yml  # OSRM self-hosted (Vietnam OSM)
```

## 🔐 Bí mật và cấu hình

Ba thứ **không** nằm trong kho, cố ý (xem `.gitignore`):

| Tệp | Lộ ra thì sao |
|---|---|
| `bb-core/.env` | Chứa `JWT_SECRET`. Lộ khoá ký token nghĩa là ai cũng tự tạo được token của bất kỳ ai |
| `bb-sos/android/app/*.jks` | Khoá ký APK. Lộ ra thì người khác ký được bản cài mạo danh, Android coi đó là bản cập nhật hợp lệ |
| `bb-sos/android/key.properties` | Mật khẩu của khoá ký trên |

Chép `bb-core/.env.example` thành `.env` rồi điền. Máy chủ **từ chối khởi động**
nếu `JWT_SECRET` còn giá trị mặc định — sinh khoá thật bằng:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **Tài khoản dữ liệu mẫu** (`admin` / `bloodblink@2026`, `choray` / `choray@2026`)
> nằm ngay trong `app/models/seed.py`. Chấp nhận được với dữ liệu mô phỏng, nhưng
> phải đổi trước khi chạy thật hoặc trước khi mở kho ra công khai.

## ⚠️ Hạng mục còn thiếu

Ghi ở đây thay vì để người đọc tự phát hiện:

- **Đăng nhập bằng OTP là mô phỏng.** Chưa nối cổng SMS; nhập số nào cũng được và
  mã tự điền `123456`. App tự khai điều này trên màn hình thay vì giấu.
- **Định tuyến không có dữ liệu giao thông thời gian thực.** `StraightLineRouting`
  (haversine) luôn khả dụng; `OSRMRouting` cần dựng OSRM từ OSM Vietnam extract.
- **Đẩy thông báo chưa có Firebase.** Kênh `store` (app hỏi hộp thư mỗi 45 giây)
  chạy được ngay; kênh `fcm` đã viết xong nhưng dự án chưa có dự án Firebase.
- **Bảng `facility` không chạy trên SQLite** (`geoalchemy2.Geometry` + `JSONB`),
  nên test đụng cơ sở y tế phải chạy trên Postgres.

## 📄 Giấy phép

Dự án nội bộ cho mục đích thi GenD Arena 2026.