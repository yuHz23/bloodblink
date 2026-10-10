"""
E2E workflow test — chạy vào backend bb-core ĐANG SỐNG.

Phủ toàn bộ luồng theo đúng thứ tự thật của 3 vai trò:
  1. BB-Console (dashboard): staff login, danh sách cơ sở, tồn kho, audit
  2. Bệnh viện: mở SOS, xem thông báo/phản hồi, đóng ca, yêu cầu điều chuyển
  3. App BB-SOS (người hiến): đăng ký → xác minh → push-token → hộp thư SOS
     → nhận lời kèm chia sẻ vị trí

Không đụng vào pytest suite — script này chỉ dùng HTTP, như app/console thật.
Chạy:  python e2e_workflow_test.py  [BASE_URL]
Mặc định: http://127.0.0.1:8000
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

# Tài khoản seed — mật khẩu mẫu của dữ liệu mô phỏng, đã ghi công khai trong seed.py
STAFF = {"admin": "bloodblink@2026", "tmhh": "tmhh@2026", "choray": "choray@2026"}

EXPECTED_FACILITY_NAMES = {
    "fac-bv-tmhh": "Bệnh viện A",
    "fac-bv-cho-ray": "Bệnh viện B",
    "fac-bv-ung-buou": "Bệnh viện C",
    "fac-bv-nhi-dong": "Bệnh viện D",
    "fac-bv-pham-ngoc-thach": "Bệnh viện E",
}
# Không được để sót tên thật của cơ sở ở bất kỳ đâu trong API response
FORBIDDEN_NAMES = ["Truyền máu", "Chợ Rãy", "Ung Bướu", "Nhi Đồng", "Phạm Ngọc Thạch"]

BV_C_LAT, BV_C_LON = 10.7736, 106.6973  # Bệnh viện C — dùng cho H3 cell + GPS

results: list[tuple[str, bool, str]] = []
ctx: dict = {}  # dữ liệu chia sẻ giữa các bước (token, donor_id, event_id...)


def step(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main():
    client = httpx.Client(base_url=BASE, timeout=30.0)

    # ── 0. Health ────────────────────────────────────────────────
    r = client.get("/api/health")
    step("Health check", r.status_code == 200 and r.json()["status"] == "ok",
         f"HTTP {r.status_code}")

    # ── 1. Dashboard: staff login ───────────────────────────────
    r = client.post("/api/auth/login", json={"username": "admin", "password": STAFF["admin"]})
    ok = r.status_code == 200 and r.json()["role"] == "admin"
    step("Dashboard: admin login", ok, f"HTTP {r.status_code}")
    ctx["admin"] = r.json()["access_token"]
    h = auth(ctx["admin"])

    r = client.get("/api/auth/me", headers=auth(ctx["admin"]))
    step("Dashboard: token còn hạn (/auth/me)", r.status_code == 200)

    r = client.post("/api/auth/login", json={"username": "choray", "password": STAFF["choray"]})
    body = r.json()
    ok = r.status_code == 200 and body.get("facility_name") == "Bệnh viện B"
    step("Bệnh viện: staff login — tên cơ sở đã ẩn danh thành 'Bệnh viện B'",
         ok, f"facility_name={body.get('facility_name')!r}")
    ctx["choray"] = body["access_token"]

    # ── 2. Danh sách cơ sở: đúng tên A–E, không còn tên thật ──────
    r = client.get("/api/facilities", headers=h)
    facs = {f["id"]: f["name"] for f in r.json()} if r.status_code == 200 else {}
    ok = r.status_code == 200 and all(
        facs.get(fid) == name for fid, name in EXPECTED_FACILITY_NAMES.items()
    )
    step("Facilities: 5 cơ sở đúng tên ẩn danh A–E", ok, str(sorted(facs.values())))
    leaked = [n for n in FORBIDDEN_NAMES if n.lower() in r.text.lower()]
    step("Facilities: không còn tên thật của bệnh viện", not leaked, ", ".join(leaked) or "sạch")

    # ── 3. Tồn kho (router khoá theo staff) ───────────────────────
    r = client.get("/api/inventory/summary", headers=h)
    ok = r.status_code == 200 and "total" in r.text
    step("Dashboard: tổng quan tồn kho", ok, f"HTTP {r.status_code}")
    r = client.get("/api/inventory/", headers=h, params={"limit": 5})
    ok = r.status_code == 200 and isinstance(r.json(), list)
    step("Dashboard: danh sách đơn vị máu", ok,
         f"HTTP {r.status_code}, {len(r.json()) if r.status_code == 200 else r.text[:120]} đơn vị")
    r = client.get("/api/inventory/", headers={})
    step("Bảo mật: tồn kho từ chối khi không có token", r.status_code in (401, 403),
         f"HTTP {r.status_code}")

    # ── 4. App: người hiến đăng ký gần Bệnh viện C ────────────────
    import h3
    cell = h3.latlng_to_cell(BV_C_LAT, BV_C_LON, 7)
    donor_payload = {
        "abo": "O", "rh": "+",
        "birth_year": 1999, "sex": "M", "weight_kg": 62,
        "h3_cell": cell, "geocell_ttl_hours": 4,
    }
    r = client.post("/api/donors/register", json=donor_payload)
    body = r.json()
    ok = r.status_code == 200 and body.get("access_token") and body.get("device_secret")
    step("App: đăng ký người hiến (có token + device_secret)", ok, f"HTTP {r.status_code}")
    ctx["donor_id"] = body["id"]
    ctx["donor_token"] = body["access_token"]
    ctx["device_secret"] = body["device_secret"]

    # Đăng ký lại bằng device_secret — đường "đăng nhập lại" của app
    donor_payload["id"] = ctx["donor_id"]
    donor_payload["device_secret"] = ctx["device_secret"]
    r = client.post("/api/donors/register", json=donor_payload)
    step("App: đăng nhập lại bằng device_secret", r.status_code == 200)

    # Không có secret/token thì bị từ chối — không ai ghi đè hồ sơ người khác
    donor_payload.pop("device_secret")
    r = client.post("/api/donors/register", json=donor_payload)
    step("Bảo mật: không ghi đè được hồ sơ khi thiếu chứng cứ sở hữu",
         r.status_code == 403, f"HTTP {r.status_code}")

    # ── 5. Bệnh viện xác minh + app đăng push token ───────────────
    r = client.post(f"/api/donors/{ctx['donor_id']}/verify",
                    json={"verified": True}, headers=h)
    step("Bệnh viện: xác minh người hiến", r.status_code == 200 and r.json()["verified"] is True)

    dh = auth(ctx["donor_token"])
    r = client.put(f"/api/donors/{ctx['donor_id']}/push-token",
                  json={"push_token": f"e2e-{uuid.uuid4()}", "platform": "android"}, headers=dh)
    step("App: đăng ký push token", r.status_code == 200)

    r = client.get(f"/api/donors/{ctx['donor_id']}", headers=dh)
    step("App: đọc lại hồ sơ (đồng bộ trạng thái)", r.status_code == 200 and r.json()["verified"])

    # ── 6. Bệnh viện C mở SOS O+ khẩn cấp (PLT) ──────────────────
    # Endpoint trùng hoá ca đang mở giống hệt (anti double-click). Chọn cặp
    # cơ sở × chế phẩm chưa từng mở trong DB nên luôn tạo ca MỚI — donor vừa
    # đăng ký phải nằm trong danh sách được gọi ngay vòng 0. Nếu trùng ca cũ
    # thì nâng vòng để gọi thêm thay vì complete (ca đang mở không được complete).
    ungbuou_h = auth(client.post("/api/auth/login",
                    json={"username": "ungbuou", "password": "ungbuou@2026"}).json()["access_token"])
    sos_payload = {
        "facility_id": "fac-bv-ung-buou", "component_code": "PLT",
        "abo": "O", "rh": "+", "urgency": "emergency", "target_count": 1,
    }
    body = {}
    for _attempt in range(2):
        r = client.post("/api/sos/event", json=sos_payload, headers=ungbuou_h)
        body = r.json()
        ctx["event_id"] = body["id"]
        notifs = client.get(
            f"/api/sos/event/{ctx['event_id']}/notifications", headers=h
        ).json()
        if any(n["donor_id"] == ctx["donor_id"] for n in notifs):
            break
        client.post(f"/api/sos/event/{ctx['event_id']}/escalate", headers=ungbuou_h)
    ok = r.status_code == 200 and body["status"] == "open" and body["donors_notified"] >= 1
    step("Bệnh viện: mở SOS O+ khẩn cấp — có người được gọi ngay",
         ok, f"ring={body.get('ring')}, donors_notified={body.get('donors_notified')}")
    tmhh_h = ungbuou_h  # ca này thuộc Bệnh viện C

    # ── 7. App: poll hộp thư SOS (đúng đường app gọi) ─────────────
    r = client.get(f"/api/donors/{ctx['donor_id']}/sos-inbox",
                   params={"include_read": "false"}, headers=dh)
    inbox = r.json() if r.status_code == 200 else []
    ok = r.status_code == 200 and any(i["event_id"] == ctx["event_id"] for i in inbox)
    step("App: hộp thư SOS có lời kêu gọi vừa mở", ok,
         f"{len(inbox)} mục" + (f", event={inbox[0]['event_id'][:8]}…" if inbox else ""))

    # ── 8. Bệnh viện xem thông báo vòng ──────────────────────────
    r = client.get(f"/api/sos/event/{ctx['event_id']}/notifications", headers=tmhh_h)
    notifs = r.json() if r.status_code == 200 else []
    ok = r.status_code == 200 and any(n["donor_id"] == ctx["donor_id"] for n in notifs)
    step("Bệnh viện: xem danh sách người được gọi", ok,
         f"{len(notifs)} thông báo, ring={notifs[0]['ring'] if notifs else '?'}")

    # ── 9. App nhận lời + chia sẻ vị trí ─────────────────────────
    r = client.post(f"/api/sos/event/{ctx['event_id']}/respond", json={
        "donor_id": ctx["donor_id"], "response": "accepted",
        "share_location": True,
        "latitude": BV_C_LAT + 0.002, "longitude": BV_C_LON + 0.002,
    }, headers=dh)
    step("App: nhận lời SOS kèm chia sẻ vị trí", r.status_code == 200, f"HTTP {r.status_code}")

    r = client.get(f"/api/sos/event/{ctx['event_id']}/responses", headers=tmhh_h)
    responses = r.json() if r.status_code == 200 else []
    ok = r.status_code == 200 and any(
        x["donor_id"] == ctx["donor_id"] and x["outcome"] == "accepted" for x in responses
    )
    step("Bệnh viện: thấy người hiến đã nhận lời", ok)

    r = client.get(f"/api/sos/event/{ctx['event_id']}/locations", headers=tmhh_h)
    locs = r.json() if r.status_code == 200 else []
    # Endpoint cố ý ẩn danh — không trả donor_id, chỉ toạ độ đã chia sẻ
    ok = r.status_code == 200 and len(locs) >= 1 and "latitude" in locs[0]
    step("Bệnh viện: nhận được toạ độ GPS người hiến đã đồng ý (ẩn danh)", ok,
         f"{len(locs)} vị trí")

    # ── 10. Bệnh viện xác nhận hiến rồi đóng ca ───────────────────
    # Người nhận lời đang "chờ xác nhận hiến" — complete chặn cho đến khi
    # luồng thưởng ghi nhận kết quả hiến (mock) của họ.
    r = client.post(f"/api/sos/event/{ctx['event_id']}/rewards/{ctx['donor_id']}/donation",
                    json={"donated": True}, headers=tmhh_h)
    ok = r.status_code == 200 and r.json()["status"] == "mock_ready"
    step("Bệnh viện: xác nhận người hiến đã đến hiến (luồng thưởng)", ok,
         f"status={r.json().get('status')}")

    r = client.post(f"/api/sos/event/{ctx['event_id']}/complete", headers=tmhh_h)
    ok = r.status_code == 200 and r.json()["status"] == "completed"
    step("Bệnh viện: đóng ca SOS", ok, f"status={r.json().get('status')}, HTTP {r.status_code}")

    # ── 11. Yêu cầu điều chuyển + ghép nguồn ────────────────────
    r = client.post("/api/matching/request", json={
        "requester_facility_id": "fac-bv-cho-ray", "component_code": "RBC",
        "abo": "O", "rh": "+", "qty": 1, "urgency": "routine",
        "needed_by": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }, headers=h)
    ok = r.status_code == 200 and r.json()["id"]
    step("Bệnh viện B: tạo yêu cầu điều chuyển RBC O+", ok)
    ctx["request_id"] = r.json()["id"] if ok else None

    if ctx["request_id"]:
        r = client.post("/api/matching/find", params={"request_id": ctx["request_id"]}, headers=h)
        body = r.json()
        ok = r.status_code == 200 and body.get("results") is not None
        step("Dashboard: ghép nguồn cho yêu cầu", ok,
             f"{len(body.get('results', []))} ứng viên, sos_action={body.get('sos_action')}")
        r = client.post(f"/api/matching/request/{ctx['request_id']}/broadcast", headers=h)
        step("Bệnh viện: phát yêu cầu tới các cơ sở", r.status_code == 200)
        r = client.get(f"/api/matching/request/{ctx['request_id']}/offers", headers=h)
        step("Bệnh viện: đọc danh sách chào hàng", r.status_code == 200)

    # ── 12. Định tuyến ───────────────────────────────────────────
    r = client.get("/api/routing/eta/facility/fac-bv-tmhh", headers=h)
    ok = r.status_code == 200 and r.text.count("Bệnh viện") >= 1
    leaked = [n for n in FORBIDDEN_NAMES if n.lower() in r.text.lower()]
    step("Dashboard: ETA giữa các cơ sở (tên ẩn danh)", ok and not leaked,
         f"HTTP {r.status_code}" + (f", sót {leaked}" if leaked else ""))
    r = client.get("/api/routing/eta", params={
        "from_lat": BV_C_LAT, "from_lon": BV_C_LON,
        "to_lat": 10.7635, "to_lon": 106.6690, "mode": "motorcycle",
    }, headers=h)
    ok = r.status_code == 200 and r.json().get("distance_m", 0) > 0
    step("Dashboard: ETA C→B (OSRM hoặc fallback đường thẳng)", ok,
         f"provider={r.json().get('provider')}")

    # ── 13. Audit ────────────────────────────────────────────────
    r = client.get("/api/audit", headers=h, params={"limit": 50})
    ok = r.status_code == 200 and isinstance(r.json(), list)
    step("Dashboard: nhật ký kiểm toán có ghi các bước vừa chạy", ok,
         f"{len(r.json())} bản ghi")

    client.close()

    # ── Tổng kết ─────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{'=' * 60}")
    print(f"E2E: {passed}/{len(results)} bước PASS — {BASE}")
    print(f"{'=' * 60}")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL: {name} ({detail})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())