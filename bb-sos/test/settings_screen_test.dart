/// BB-SOS — Widget test cho màn Cài đặt sau khi thu gọn.
///
/// App người hiến chỉ còn Hồ sơ, Lịch sử và Cài đặt; phần quy tắc khoảng cách
/// hiến / chi tiết H3 đã bỏ. Test này khoá lại phạm vi đó: không đưa được
/// các phần của nhân viên/cơ sở y tế quay lại màn Cài đặt một cách vô tình.

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:bb_sos/screens/settings_screen.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final dir = await Directory.systemTemp.createTemp('bb-sos-settings-test');
    Hive.init(dir.path);

    // Máy ảo test không chạy trên Android nên mọi lời gọi kênh nền phải được
    // giả lập: thông báo luôn "cấp quyền thành công", phiên bản đọc từ
    // package_info trả đúng 1.5.2 (build 11).
    TestWidgetsFlutterBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('flutter_local_notifications'),
      (call) async => true,
    );
    TestWidgetsFlutterBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/package_info'),
      (call) async => {
        'appName': 'BLOODBLINK SOS',
        'packageName': 'vn.bloodblink.sos',
        'version': '1.5.2',
        'buildNumber': '11',
      },
    );
  });

  Future<void> pumpSettings(WidgetTester tester) async {
    // Màn Cài đặt dài hơn viewport mặc định 800x600 của test; ListView không
    // dựng phần dưới màn nên cần tăng chiều cao thử để thấy đủ các thẻ.
    tester.view.physicalSize = const Size(1080, 4800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(const MaterialApp(home: SettingsScreen()));
    await tester.pumpAndSettle();
  }

  testWidgets('Chỉ còn đúng các phần của app người hiến', (tester) async {
    await pumpSettings(tester);

    expect(find.text('Kết nối'), findsOneWidget);
    expect(find.text('Thông báo'), findsOneWidget);
    expect(find.text('Quyền riêng tư'), findsOneWidget);
    expect(find.text('Thông tin ứng dụng'), findsOneWidget);
    expect(find.text('Chia sẻ vị trí (ô lưới H3)'), findsOneWidget);

    // Phần quy tắc hiến và chi tiết H3 đã bỏ — không quay lại được.
    expect(find.text('Khoảng cách hiến (Điều 6)'), findsNothing);
    expect(find.text('Độ phân giải H3'), findsNothing);
    expect(find.textContaining('O⁻'), findsNothing);

    // Quyền thông báo Android hiển thị trạng thái, kèm nút gửi thử.
    expect(find.text('Quyền thông báo Android'), findsOneWidget);
    expect(find.text('Gửi thông báo thử'), findsOneWidget);
  });

  testWidgets('Bật chia sẻ vị trí được lưu ngay vào máy', (tester) async {
    await pumpSettings(tester);

    await tester.tap(find.text('Chia sẻ vị trí (ô lưới H3)'));
    await tester.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('location_sharing'), isTrue);
    expect(find.byIcon(Icons.location_on), findsOneWidget);
  });
}