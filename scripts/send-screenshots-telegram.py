#!/usr/bin/env python3
"""
Gửi ảnh chụp giao diện BLOODBLINK về Telegram.

Dùng:
    python scripts/send-screenshots-telegram.py <BOT_TOKEN> [CHAT_ID] [THU_MUC]

Gửi theo nhóm 10 ảnh (giới hạn của sendMediaGroup), kèm chú thích cho ảnh đầu
mỗi nhóm. Token KHÔNG được ghi vào tệp nào — truyền qua tham số dòng lệnh.
"""

import json
import sys
import time
from pathlib import Path

import httpx

DEFAULT_CHAT_ID = "5187623922"
DEFAULT_DIR = Path.home() / "Downloads" / "BLOODBLINK-screenshots"

GROUPS = [
    ("console-light", "BLOODBLINK — BB-Console (chủ đề sáng)\n"
                      "Tổng quan · Tìm người hiến · SOS · Tồn kho FEFO · Ghép nguồn · Định tuyến"),
    ("console-dark", "BB-Console (chủ đề tối)\nCùng 6 màn hình, dùng token màu ngữ nghĩa"),
    ("app-light", "App BB-SOS v1.3 (chủ đề sáng)\nTrang chủ · Hồ sơ · Lịch sử · Cài đặt"),
    ("app-dark", "App BB-SOS (chủ đề tối)\nMàu lấy từ theme, không còn cắm cứng"),
]


def send_group(client, token, chat_id, files, caption):
    media, payload = [], {}
    for i, path in enumerate(files):
        key = f"file{i}"
        item = {"type": "photo", "media": f"attach://{key}"}
        if i == 0:
            item["caption"] = caption
        media.append(item)
        payload[key] = (path.name, path.read_bytes())

    r = client.post(
        f"https://api.telegram.org/bot{token}/sendMediaGroup",
        data={"chat_id": chat_id, "media": json.dumps(media)},
        files=payload,
        timeout=120,
    )
    ok = r.json().get("ok", False)
    print(f"  {caption.splitlines()[0]}: {len(files)} ảnh → {'OK' if ok else r.text[:200]}")
    return ok


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    token = sys.argv[1]
    chat_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHAT_ID
    folder = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_DIR

    if not folder.exists():
        print(f"Không thấy thư mục {folder}")
        sys.exit(1)

    with httpx.Client() as client:
        me = client.get(f"https://api.telegram.org/bot{token}/getMe", timeout=30).json()
        if not me.get("ok"):
            print(f"Token không dùng được: {me}")
            sys.exit(1)
        print(f"Bot: @{me['result']['username']} → chat {chat_id}\n")

        sent = 0
        for prefix, caption in GROUPS:
            files = sorted(folder.glob(f"{prefix}-*"))
            if not files:
                continue
            if send_group(client, token, chat_id, files, caption):
                sent += len(files)
            time.sleep(1)          # tránh chạm giới hạn tần suất của Telegram

        print(f"\nĐã gửi {sent} ảnh.")


if __name__ == "__main__":
    main()
