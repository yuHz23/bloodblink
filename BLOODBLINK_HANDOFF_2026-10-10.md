# BLOOD-BLINK SOS — bàn giao ngày 10/10/2026

## Mục tiêu người dùng

- Sửa app S10+ không đồng bộ hồ sơ, không tải danh sách cơ sở và không nhận SOS.
- Thu gọn app người hiến còn **Hồ sơ**, **Lịch sử hiến**, **Cài đặt thông báo** và **chia sẻ vị trí**. Không đưa tính năng nhân viên/cơ sở y tế vào app này.
- Tạo APK arm64 để cài trên Galaxy S10+ SM-G975F.
- Thêm workflow tự kiểm tra backend và app.
- Người dùng không có cáp USB; cần dùng Android Wireless debugging để lấy log/cài APK qua ADB.

## Nguyên nhân đã xác nhận

1. **Android chặn kết nối HTTP tới API mặc định.** App mặc định dùng `http://desktop-kijp57s.tail85e1ba.ts.net:8000/api`; DNS phân giải thành `100.106.118.107`. `network_security_config.xml` ban đầu chỉ cho phép HTTP tới host laptop `laptop-rrqk96mj.tail85e1ba.ts.net` / `100.101.73.36`, không cho host/IP mặc định. Vì vậy app phát hành có thể không gọi được API dù máy chủ sống.
2. **Backend hiện không gửi push nền bằng Firebase.** `bb-core/app/services/push.py` chọn `StorePushProvider` mặc định. `bb-sos/lib/services/sos_inbox_service.dart` hỏi hộp thư mỗi 45 giây và tự hiện local notification. Cách này chỉ hoạt động khi app/process còn chạy; app bị hệ thống dừng thì lời gọi nằm trong hộp thư tới lần mở sau. Chưa có cấu hình Firebase client/service account.
3. **Danh sách cơ sở cần phiên người hiến.** Gọi `GET /api/facilities` không có bearer token trả `401`; hồ sơ cần đăng ký thành công trước để app lưu token. Trong lần probe từ máy tính, host API mặc định trả lời được, chứng tỏ DNS/port đang thông từ máy tính.
4. **Điều kiện được gọi SOS:** backend chỉ chọn donor đã `verified`, đủ điều kiện hiến và có geocell còn TTL cho các vòng tìm theo vị trí. Người hiến mới đăng ký mặc định `verified=False`; cần nhân viên/cơ sở xác minh trước khi dùng làm người nhận thử.
5. **ADB không có thiết bị đang kết nối.** Thử kết nối lại cổng cũ `10.4.9.20:34431` không đưa S10+ lên `adb devices`. Pairing code/port cũ đã hết hạn. APK không thể tự cấp quyền ADB; cần ghép đôi lại trong Wireless debugging.

## Thay đổi đang có trong working tree

Các mục dưới đây đã chỉnh nhưng **chưa chạy analyze/test/build**:

- `bb-sos/lib/main.dart`: bỏ tab Trang chủ khỏi điều hướng; app mở vào Hồ sơ, còn Lịch sử và Cài đặt.
- `bb-sos/android/app/src/main/res/xml/network_security_config.xml`: thêm host/IP NUC mặc định và IP LAN hiện tại `10.4.11.37` vào allowlist HTTP có phạm vi cụ thể.
- `bb-sos/lib/services/sos_inbox_service.dart`: thêm kiểm tra/cấp quyền thông báo, thông báo thử; tôn trọng hai công tắc thông báo trong Cài đặt.
- `bb-sos/lib/screens/settings_screen.dart`: hiển thị quyền Android và nút thông báo thử; đổi nhãn FCM gây hiểu nhầm thành thông báo SOS.
- `bb-sos/pubspec.yaml`: tăng app lên `1.5.2+11`; bỏ các gói Firebase/permission handler chưa được dùng. `flutter pub get` đã chạy thành công và cập nhật `pubspec.lock`.

Các sửa đổi hiện có ở `bb-console/` và `bb-core/` đã tồn tại trước lượt app này. Giữ nguyên; không reset/revert chúng. `.gitignore` đã thêm `.venv_wsl/` và `/cloudflared.exe` để bỏ môi trường/công cụ máy cá nhân khỏi Git. Repo hiện ở nhánh `feature/map-sos-northflank`.

## Việc tiếp tục theo thứ tự

1. Rà lại các diff hiện có và hoàn thiện giao diện tối giản. Người dùng chỉ yêu cầu Hồ sơ, Lịch sử hiến, Cài đặt thông báo và vị trí; Settings hiện còn phần quy tắc khoảng cách hiến/H3 có thể bỏ.
2. Chạy `flutter pub get`, `flutter analyze`, `flutter test` trong `bb-sos`; sửa lỗi do thay đổi hiện tại.
3. Chạy `python -m pytest` trong `bb-core` (Python 3.12+; test dependencies trong `requirements-dev.txt`).
4. Tạo `.github/workflows/ci.yml`: Python 3.12 + pytest ở `bb-core`; Flutter stable + `flutter analyze`, `flutter test` và build arm64 ở `bb-sos`. Chưa thấy workflow trong working tree hiện tại.
5. Build APK arm64 version `1.5.2+11`. Flutter CLI từng báo lỗi chung “settings are not yet available for build”; lần build trước dùng `android/gradlew :app:assembleRelease --no-daemon` và NDK 28.2.13676358 thành công. Kiểm tra APK output, chữ ký, ABI và cài đè được.
6. APK cũ (chưa có các sửa mới) nằm ở `C:\Users\Ryan\Downloads\BLOOD-BLINK-SOS-2026-10-10-arm64.apk`, version `1.5.1+10`; không dùng nhầm làm bản sửa.
7. Để kiểm thử S10+ không dây, yêu cầu người dùng bật **Developer options → Wireless debugging → Pair device with pairing code** và gửi pairing IP:port + mã sáu số cùng IP:debug port hiện tại. Dùng `adb pair <ip>:<pair-port> <code>`, sau đó `adb connect <ip>:<debug-port>`; hai port khác nhau và thay đổi theo phiên. Cài APK/logcat sau khi `adb devices -l` hiện thiết bị.
8. Để nhận SOS khi app bị đóng, cần chủ dự án cấp `google-services.json`, Firebase project ID và service-account credential cho backend qua secret/env; không commit service-account JSON. Sau đó nối FCM client token với `/donors/{id}/push-token` và bật backend `PUSH_PROVIDER=fcm`.
9. Máy chủ mặc định là Tailscale. S10+ cần ở cùng tailnet để gọi `desktop-kijp57s.tail85e1ba.ts.net`; IP LAN `10.4.11.37` chỉ là địa chỉ hiện tại của máy dev, có thể thay đổi. Kiểm tra Windows Firewall/port 8000 nếu dùng LAN.

## Workflow kiểm chứng đề xuất

- Backend: `python -m pip install -r requirements.txt -r requirements-dev.txt`, rồi `python -m pytest -q`.
- App: `flutter pub get`, `flutter analyze --no-pub`, `flutter test --no-pub`, rồi build APK release arm64.
- Chỉ tạo workflow local thì GitHub Actions chưa chạy; cần push branch hoặc mở PR để kích hoạt remote run. Người dùng yêu cầu commit, chưa yêu cầu push remote.

## Ranh giới an toàn

- Không đưa pairing code, bearer token, device secret hoặc Firebase service-account key vào handout/log/commit.
- Không đưa `.venv_wsl/` hay executable `cloudflared.exe` vào Git nếu không có lý do phát hành rõ ràng. Đây là file môi trường/công cụ cục bộ, không phải mã nguồn ứng dụng.
- Không khẳng định đã test trên S10+ cho đến khi Wireless debugging kết nối lại.
