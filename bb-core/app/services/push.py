"""
BB-Core — Kênh đẩy thông báo tới người hiến.

Cùng khuôn với `services/routing.py` (StraightLine ↔ OSRM): một giao diện, hai
cách hiện thực, chọn bằng cấu hình.

  - `StorePushProvider` (mặc định): ghi lời kêu gọi vào bảng `sos_notification`.
    App BB-SOS hỏi hộp thư của chính mình rồi tự dựng thông báo trên máy. Không
    cần Firebase, chạy được ngay — đổi lại chỉ nhận được khi app còn sống.

  - `FcmPushProvider`: đẩy qua Firebase Cloud Messaging HTTP v1. Cần
    `fcm_credentials_path` trỏ tới service-account JSON. Dự án hiện CHƯA có
    Firebase (không có google-services.json, gradle chưa gắn plugin), nên bật
    kênh này lên mà thiếu tệp thì provider báo lỗi rõ ràng thay vì im lặng.

Dù chọn kênh nào, bảng `sos_notification` vẫn được ghi — nó là nhật ký ghi vết
"ai đã được gọi", không chỉ là hộp thư.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from app.config import settings


@dataclass
class PushMessage:
    """Nội dung một lời kêu gọi gửi tới một thiết bị."""
    token: Optional[str]
    title: str
    body: str
    data: dict[str, str]


@dataclass
class PushResult:
    ok: bool
    channel: str
    error: Optional[str] = None


class PushProvider(Protocol):
    name: str

    async def send(self, message: PushMessage) -> PushResult: ...


class StorePushProvider:
    """
    Không gửi đi đâu cả — chỉ xác nhận đã ghi vào hộp thư.

    Việc ghi bảng do tầng gọi (`services/sos_dispatch.py`) làm, nên provider này
    không cần chạm cơ sở dữ liệu.
    """

    name = "store"

    async def send(self, message: PushMessage) -> PushResult:
        return PushResult(ok=True, channel=self.name)


class FcmPushProvider:
    """
    Firebase Cloud Messaging HTTP v1.

    Chưa dùng được cho tới khi dự án có Firebase; giữ ở đây để P2 không phải
    viết lại khi có credentials, và để chỗ nối rõ ràng.
    """

    name = "fcm"

    def __init__(self, credentials_path: str = "", project_id: str = ""):
        self.credentials_path = credentials_path or settings.fcm_credentials_path
        self.project_id = project_id or settings.fcm_project_id

    @property
    def configured(self) -> bool:
        return bool(self.credentials_path and os.path.exists(self.credentials_path)
                    and self.project_id)

    async def send(self, message: PushMessage) -> PushResult:
        if not self.configured:
            return PushResult(
                ok=False, channel=self.name,
                error="Chưa cấu hình FCM: cần fcm_credentials_path (service-account JSON) "
                      "và fcm_project_id. Xem README mục 'Đẩy thông báo'.",
            )
        if not message.token:
            return PushResult(ok=False, channel=self.name,
                              error="Người hiến chưa đăng ký thiết bị nhận thông báo")

        # Gửi thật cần google-auth để lấy access token OAuth2 rồi POST tới
        # https://fcm.googleapis.com/v1/projects/{project_id}/messages:send
        try:
            import httpx
            from google.oauth2 import service_account          # type: ignore
            from google.auth.transport.requests import Request  # type: ignore
        except ImportError as exc:
            return PushResult(ok=False, channel=self.name,
                              error=f"Thiếu thư viện cho FCM ({exc.name}); cài google-auth")

        creds = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        creds.refresh(Request())

        payload = {
            "message": {
                "token": message.token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
                "android": {"priority": "high"},
            }
        }
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {creds.token}"},
            )
        if resp.status_code >= 400:
            return PushResult(ok=False, channel=self.name,
                              error=f"FCM {resp.status_code}: {resp.text[:200]}")
        return PushResult(ok=True, channel=self.name)


_provider: Optional[PushProvider] = None


def get_push_provider() -> PushProvider:
    """Provider dùng chung, chọn theo `settings.push_provider`."""
    global _provider
    if _provider is None:
        _provider = (FcmPushProvider() if settings.push_provider == "fcm"
                     else StorePushProvider())
    return _provider


def set_push_provider(provider: PushProvider) -> None:
    """Đổi provider — dùng trong test và endpoint quản trị."""
    global _provider
    _provider = provider
