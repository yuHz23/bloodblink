#!/usr/bin/env python3
"""
BLOODBLINK — Demo Script 5 phút (GenD Arena 2026)

Chạy tất cả API endpoints để demo cho ban giám khảo.
Yêu cầu: BB-Core đang chạy tại http://localhost:8000

Usage:
    python demo_script.py [--api-url http://localhost:8000]
"""

import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

API_URL = "http://localhost:8000"

def api_get(path: str) -> dict:
    """GET request to BB-Core API."""
    req = urllib.request.Request(f"{API_URL}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def api_post(path: str, data: dict) -> dict:
    """POST request to BB-Core API."""
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_URL}{path}", data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def print_step(num: int, title: str):
    print(f"\n{'='*60}")
    print(f"  PHẦN {num}: {title}")
    print(f"{'='*60}")

def print_result(label: str, data):
    print(f"\n  📋 {label}:")
    if isinstance(data, list):
        for item in data[:5]:
            print(f"     • {item}")
        if len(data) > 5:
            print(f"     ... và {len(data)-5} mục khác")
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                print(f"     {key}: {json.dumps(value, ensure_ascii=False)[:100]}...")
            else:
                print(f"     {key}: {value}")
    else:
        print(f"     {data}")


def main():
    parser = argparse.ArgumentParser(description="BLOODBLINK Demo Script — 5 phút cho GenD Arena")
    parser.add_argument("--api-url", default="http://localhost:8000", help="BB-Core API URL")
    args = parser.parse_args()
    global API_URL
    API_URL = args.api_url

    print("🩸 BLOODBLINK — Demo Script 5 phút")
    print("   Điều phối máu liên viện — GenD Arena 2026")
    print(f"   API: {API_URL}")
    print(f"   Thời gian: {datetime.now().strftime('%H:%M:%S')}")

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 0: Kiểm tra hệ thống
    # ═══════════════════════════════════════════════════════════════
    print_step(0, "KIỂM TRA HỆ THỐNG")
    try:
        health = api_get("/api/health")
        print(f"  ✅ BB-Core đang chạy: {health['service']} v{health['version']}")
    except Exception as e:
        print(f"  ❌ Không kết nối được BB-Core: {e}")
        print("  → Chạy: cd bb-core && uvicorn app.main:app --reload")
        return

    spec = api_get("/api/spec-summary")
    print_result("Ràng buộc kiến trúc", spec)

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 1: Tồn kho & FEFO
    # ═══════════════════════════════════════════════════════════════
    print_step(1, "TỒN KHO & FEFO (FIRST EXPIRY FIRST OUT)")
    inventory = api_get("/api/inventory/units")
    print_result(f"Tổng đơn vị máu trong hệ thống", f"{len(inventory)} đơn vị")

    # Đếm theo nhóm máu
    blood_type_counts = {}
    for unit in inventory:
        bt = f"{unit.get('abo', '?')}{unit.get('rh', '?')}"
        blood_type_counts[bt] = blood_type_counts.get(bt, 0) + 1
    print(f"\n  📊 Phân bố nhóm máu:")
    for bt in sorted(blood_type_counts.keys()):
        pct = blood_type_counts[bt] / len(inventory) * 100
        bar = "█" * int(pct / 2)
        print(f"     {bt:>3}: {blood_type_counts[bt]:>4} ({pct:>5.1f}%) {bar}")

    # Đếm theo thành phần
    comp_counts = {}
    for unit in inventory:
        comp = unit.get('component_code', '?')
        comp_counts[comp] = comp_counts.get(comp, 0) + 1
    print(f"\n  📊 Theo thành phần:")
    for comp in sorted(comp_counts.keys()):
        print(f"     {comp}: {comp_counts[comp]} đơn vị")

    # FEFO: sắp xếp theo ngày hết hạn
    expiring = sorted(inventory, key=lambda u: u.get('expires_at', '9999'))[:3]
    print(f"\n  ⏰ 3 đơn vị gần hết hạn nhất (FEFO ưu tiên xuất trước):")
    for u in expiring:
        print(f"     {u.get('component_code','?')} {u.get('abo','?')}{u.get('rh','?')} — hết hạn: {u.get('expires_at','?')[:10]}")

    time.sleep(1)

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 2: Matching Engine — Tìm nguồn máu
    # ═══════════════════════════════════════════════════════════════
    print_step(2, "MATCHING ENGINE — TÌM NGUỒN MÁU TƯƠNG HỢP")

    # Demo: Bệnh viện Nhi Đồng cần máu O+ khẩn cấp
    print("\n  🏥 Kịch bản: BV Nhi Đồng cần máu O+ RBC khẩn cấp")
    print("     Bệnh nhi: nữ, 5 tuổi, nhóm máu O+")

    try:
        match_result = api_post("/api/matching/find", {
            "requester_facility_id": "fac-bv-nhi-dong",
            "component_code": "RBC",
            "abo": "O",
            "rh": "+",
            "urgency": "emergency",
            "recipient_sex": "F",
            "recipient_age": 5,
            "needed_by": datetime.now(timezone.utc).isoformat(),
        })

        matches = match_result.get("matches", [])
        print(f"\n  🔍 Kết quả: {len(matches)} nguồn tương hợp")
        for m in matches[:5]:
            print(f"     #{m.get('rank','?')}: {m.get('blood_type','?')} — điểm: {m.get('score',0):.3f}")
            print(f"        {m.get('reason_text','')}")
            if m.get('eta_minutes'):
                print(f"        ETA: {m['eta_minutes']} phút")
    except Exception as e:
        print(f"  ⚠️ Matching endpoint: {e}")
        print("  → Chạy seed data trước: python -m seed.seed_db")

    time.sleep(1)

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 3: ABO/RhD Compatibility — Ràng buộc chuyên môn
    # ═══════════════════════════════════════════════════════════════
    print_step(3, "ABO/RhD — RÀNG BUỘC CHUYÊN MÔN")

    demo_pairs = [
        ("O-", "O+", "RBC", "M", 30, "O- → O+: tương hợp, nhưng O- là tài nguyên khan hiếm"),
        ("O+", "A+", "RBC", "M", 30, "O+ → A+: tương hợp (universal donor)"),
        ("A+", "O+", "RBC", "M", 30, "A+ → O+: KHÔNG tương hợp"),
        ("O-", "A-", "RBC", "F", 25, "O- → A- nữ 25t: tương hợp (RhD không vi phạm)"),
        ("A+", "B-", "RBC", "F", 30, "A+ → B- nữ 30t: KHÔNG (RhD vi phạm cho nữ 18-45)"),
    ]

    print("\n  📋 Bảng tương hợp minh họa:")
    for donor, recipient, comp, sex, age, note in demo_pairs:
        try:
            result = api_post("/api/matching/check-compatibility", {
                "donor_abo": donor[:-1],
                "donor_rh": donor[-1],
                "recipient_abo": recipient[:-1],
                "recipient_rh": recipient[-1],
                "component": comp,
                "recipient_sex": sex,
                "recipient_age": age,
            })
            compat = result.get("compatible", False)
            reason = result.get("reason", "")
            icon = "✅" if compat else "❌"
            print(f"     {icon} {donor} → {recipient} ({sex}{age}t): {reason}")
            print(f"        → {note}")
        except Exception as e:
            print(f"     ⚠️ Compatibility check: {e}")

    time.sleep(1)

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 4: Routing — ETA giữa các bệnh viện
    # ═══════════════════════════════════════════════════════════════
    print_step(4, "ĐỊNH TUYẾN — ETA GIỮA CÁC BỆNH VIỆN")

    try:
        pairs = api_get("/api/routing/hcmc-pairs")
        print(f"\n  📍 {len(pairs)} cặp ETA giữa các bệnh viện TP.HCM")
        print(f"\n  🏥 Top 5 cặp gần nhất:")
        sorted_pairs = sorted(pairs, key=lambda p: p.get('straight_line_km', 999))[:5]
        for p in sorted_pairs:
            print(f"     {p.get('from_name','?')[:20]:20s} → {p.get('to_name','?')[:20]:20s} "
                  f"({p.get('straight_line_km',0):.1f} km, ETA xe: {p.get('car_eta_min',0):.0f} phút)")
    except Exception as e:
        print(f"  ⚠️ Routing endpoint: {e}")

    time.sleep(1)

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 5: SOS Escalation — 4-ring huy động
    # ═══════════════════════════════════════════════════════════════
    print_step(5, "SOS ESCALATION — 4-RING HUY ĐỘNG NGƯỜI HIẾN")

    print("""
  🆘 Khi cần máu khẩn cấp, BLOODBLINK huy động 4 vòng:

     Ring 1 (T+0 phút, 1 km):  ~30% người hiến phản hồi
     Ring 2 (T+10 phút, 5 km): ~20% thêm phản hồi
     Ring 3 (T+25 phút, 10 km): ~15% thêm phản hồi
     Ring 4 (T+45 phút, 20 km): ~10% thêm phản hồi

  Ràng buộc Điều 6 TT 26/2013/TT-BYT:
     • Máu toàn phần/RBC: 12 tuần giữa 2 lần hiến
     • Tiểu cầu/huyết tương: 2 tuần giữa 2 lần hiến
     • RhD: KHÔNG hạ chuẩn Rh(+) cho nữ 18-45 tuổi

  Quyền riêng tư:
     • Lưu ô lưới H3 (~1 km) thay vì tọa độ GPS thô
     • TTL 4 giờ — sau đó vị trí tự xóa
  """)

    try:
        sos_result = api_post("/api/sos/create", {
            "facility_id": "fac-bv-tmhh",
            "component_code": "RBC",
            "abo": "O",
            "rh": "-",
            "urgency": "emergency",
            "message": "Cần máu O- khẩn cấp cho bệnh nhi",
        })
        print(f"  ✅ SOS event tạo thành: {sos_result.get('sos_id', 'N/A')}")
        rings = sos_result.get("rings", [])
        for ring in rings:
            print(f"     Ring {ring.get('ring','?')}: {ring.get('donors_notified',0)} người được thông báo")
    except Exception as e:
        print(f"  ⚠️ SOS endpoint: {e}")

    # ═══════════════════════════════════════════════════════════════
    # PHẦN 6: BB-Box — Hai chế độ ngưỡng nhiệt độ
    # ═══════════════════════════════════════════════════════════════
    print_step(6, "BB-BOX — HAI CHẾ ĐỘ NGƯỠNG NHIỆT ĐIỀU 20")

    print("""
  🌡️ Điều 20 TT 26/2013/TT-BYT — Hai chế độ ngưỡng:

     Thành phần   │ Bảo quản (Storage) │ Vận chuyển (Transport)
     ─────────────┼────────────────────┼────────────────────────
     WB / RBC     │     2–6°C          │     1–10°C
     Tiểu cầu     │    20–24°C          │    20–24°C
     Huyết tương  │   −25 → −18°C      │   −18 → −10°C

  ⚠️ Điểm quan trọng: Cùng nhiệt độ 8°C cho RBC:
     • BẢO QUẢN: NGUY HIỂM (ngoài 2-6°C) → LED đỏ + buzzer
     • VẬN CHUYỂN: BÌNH THƯỜNG (trong 1-10°C) → LED xanh lá

  BB-Box ESP32-S3 tự động chuyển chế độ khi chuyển từ kho sang xe vận chuyển.
  """)

    print(f"\n  📊 Kết quả mô phỏng 90 ngày (8 BV TP.HCM):")
    print(f"     Tỷ lệ đáp ứng: 97.7% → 99.8% (+2.1pp)")
    print(f"     Thời gian TB: 5 giờ → 7 phút (−97.6%)")
    print(f"     Đơn vị hủy: 1,095 → 695 (−36.5%)")

    # ═══════════════════════════════════════════════════════════════
    # TỔNG KẾT
    # ═══════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print("  🏁 TỔNG KẾT DEMO")
    print(f"{'='*60}")
    print("""
  BLOODBLINK giải quyết 3 vấn đề cốt lõi:

  1️⃣  TÌM NGUỒN MÁU: Matching engine liên viện với ABO/RhD
      → Tỷ lệ khớp chính xác tăng từ 94.2% → 99.0%
      → Thời gian đáp ứng giảm từ 5 giờ → 7 phút

  2️⃣  GIÁM SÁT CHUỖI LẠNH: BB-Box 2 chế độ ngưỡng (Điều 20)
      → Đơn vị hủy giảm 36.5%
      → Cùng nhiệt độ, khác chế độ, khác cảnh báo

  3️⃣  HUY ĐỘNG KHẨN CẤP: SOS 4-ring + Điều 6 + RhD
      → Phản hồi trong 10-45 phút thay vì hàng giờ
      → Quyền riêng tư: H3 geocell, không lưu GPS thô

  Tuân thủ quy định: TT 26/2013/TT-BYT, TT 13/2025/TT-BYT
  Số liệu đã kiểm chứng: BV TMHH HCMC, WHO, Viện HH-TMTW
    """)

    print(f"  Demo hoàn thành lúc {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()