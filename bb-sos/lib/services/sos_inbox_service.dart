/// BB-SOS — Nhận lời kêu gọi hiến máu.
///
/// Dự án chưa có Firebase (không có google-services.json, gradle chưa gắn
/// plugin), nên kênh giao hàng hiện tại là: app hỏi hộp thư của chính mình trên
/// máy chủ, rồi tự dựng thông báo trên điện thoại.
///
/// Đánh đổi so với FCM, nói rõ để không nhầm khi bảo vệ đồ án:
///   - Chạy được ngay, không phụ thuộc dịch vụ ngoài, không rò dữ liệu qua Google.
///   - Nhưng CHỈ nhận được khi app còn sống. App bị tắt hẳn thì lời kêu gọi nằm
///     im trong hộp thư tới lần mở app kế tiếp.
///
/// Khi có Firebase, `ApiService.setPushToken` và endpoint `/donors/{id}/push-token`
/// đã sẵn sàng — chỉ cần đẩy token FCM lên là máy chủ chuyển sang kênh đẩy thật.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:hive/hive.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/donor_profile.dart';
import 'api_service.dart';

class SosInboxService with WidgetsBindingObserver {
  SosInboxService._();
  static final SosInboxService instance = SosInboxService._();

  final _api = ApiService();
  final _plugin = FlutterLocalNotificationsPlugin();

  /// Các lời kêu gọi đang chờ trả lời — màn hình lắng nghe cái này.
  final ValueNotifier<List<SosInboxItem>> pending = ValueNotifier([]);

  /// Mã lời kêu gọi đã dựng thông báo, để không rung lại mỗi lượt hỏi.
  final Set<String> _announced = {};

  Timer? _timer;
  String? _donorId;
  bool _ready = false;

  static const _channel = AndroidNotificationChannel(
    'bb_sos_calls',
    'Lời kêu gọi hiến máu',
    description: 'Thông báo khi có cơ sở y tế cần nhóm máu của bạn',
    importance: Importance.max,
  );

  /// Khoảng cách giữa hai lần hỏi hộp thư.
  ///
  /// 45 giây: đủ dày để bắt kịp một vòng leo thang (mốc gần nhau nhất là 10
  /// phút), đủ thưa để không hao pin.
  static const _pollInterval = Duration(seconds: 45);

  Future<void> init() async {
    if (_ready) return;

    await _plugin.initialize(
      const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/launcher_icon'),
      ),
    );

    final android = _plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    await android?.createNotificationChannel(_channel);
    await android?.requestNotificationsPermission();

    WidgetsBinding.instance.addObserver(this);
    _ready = true;
  }

  /// Bắt đầu theo dõi hộp thư. Gọi sau khi người dùng đã có hồ sơ.
  Future<void> start() async {
    await init();
    if (!await _ensureSession()) return;

    _timer?.cancel();
    _timer = Timer.periodic(_pollInterval, (_) => refresh());
    await refresh();
  }

  /// Đảm bảo máy có mã người hiến và token còn dùng được.
  ///
  /// Người dùng đã đăng ký từ bản cũ (trước khi có xác thực) thì trên máy có hồ
  /// sơ nhưng không có token — nếu không tự lấy lại, họ sẽ im lặng không bao giờ
  /// nhận được lời kêu gọi nào. `/donors/register` là upsert nên gọi lại an toàn
  /// và cấp token mới; đây cũng là đường phục hồi khi token hết hạn.
  Future<bool> _ensureSession() async {
    final prefs = await SharedPreferences.getInstance();
    _donorId = prefs.getString('donor_id');

    // `hasToken` chỉ nói "có chuỗi token trong máy", không nói nó còn dùng được.
    // Token sống 12 giờ, và trước đây không chỗ nào xoá nó khi máy chủ trả 401 —
    // nên app cứ nghĩ mình còn phiên trong khi mọi lời gọi đều bị từ chối, và
    // người hiến im lặng không nhận được lời kêu gọi nào nữa.
    if (_donorId != null && _api.hasToken && !_api.tokenRejected) return true;

    final box = await Hive.openBox<DonorProfile>('donor_profile');
    if (box.isEmpty) return false;          // chưa tạo hồ sơ — không có gì để nhận

    final profile = box.values.first;
    try {
      final result = await _api.registerDonor(
        donorId: profile.id,
        abo: profile.abo,
        rh: profile.rh,
        birthYear: profile.birthYear,
        sex: profile.sex,
        weightKg: profile.weightKg,
        h3Cell: profile.h3Cell,
      );
      _donorId = result.id;
      await prefs.setString('donor_id', result.id);
      await prefs.setBool('donor_verified', result.verified);
      return true;
    } on ApiException catch (e) {
      // 403 = máy chủ không nhận mã hồ sơ này nữa: máy cài từ bản cũ nên chưa có
      // bí mật thiết bị, mà token thì đã hết hạn. Không có đường lấy lại hồ sơ
      // cũ, nhưng để người dùng "im lặng không nhận được gì" là tệ hơn — đăng ký
      // hồ sơ mới để họ vẫn nhận được lời kêu gọi. Trạng thái xác minh phải làm
      // lại, và đó là điều đúng: cơ sở y tế xác minh thiết bị, không phải con số.
      if (e.statusCode == 403) return _registerFreshProfile(box, prefs);
      return false;                          // mất mạng — lượt sau thử lại
    }
  }

  /// Cấp hồ sơ mới khi hồ sơ cũ không còn chứng minh được quyền sở hữu.
  Future<bool> _registerFreshProfile(
    Box<DonorProfile> box,
    SharedPreferences prefs,
  ) async {
    final old = box.values.first;
    try {
      final result = await _api.registerDonor(
        donorId: '',                         // để máy chủ tự sinh mã mới
        abo: old.abo,
        rh: old.rh,
        birthYear: old.birthYear,
        sex: old.sex,
        weightKg: old.weightKg,
      );
      old.id = result.id;
      await old.save();
      _donorId = result.id;
      await prefs.setString('donor_id', result.id);
      await prefs.setBool('donor_verified', result.verified);
      return true;
    } on ApiException {
      return false;
    }
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    pending.value = [];
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Mở lại app là hỏi ngay, không đợi hết chu kỳ — đây là lúc người dùng
    // nhiều khả năng đang cầm máy nhất.
    if (state == AppLifecycleState.resumed) refresh();
  }

  /// Hỏi hộp thư một lần và dựng thông báo cho lời kêu gọi mới.
  Future<void> refresh() async {
    if (!await _ensureSession()) return;
    final donorId = _donorId!;

    try {
      final items = await _api.fetchSosInbox(donorId);
      pending.value = items;

      for (final item in items) {
        if (_announced.contains(item.notificationId)) continue;
        _announced.add(item.notificationId);
        await _show(item);
      }

      // Lời kêu gọi đã đóng thì quên đi, để lần sau có sự kiện mới vẫn báo.
      final live = items.map((i) => i.notificationId).toSet();
      _announced.retainWhere(live.contains);
    } on ApiException catch (e) {
      // Phiên vừa hết hạn giữa chừng: interceptor đã bỏ token, lấy phiên mới rồi
      // hỏi lại NGAY. Đợi tới lượt sau nghe thì nhẹ, nhưng lượt sau cũng hỏng y
      // hệt nếu không ai chủ động lấy token mới.
      if (e.statusCode == 401 && await _ensureSession()) {
        try {
          pending.value = await _api.fetchSosInbox(_donorId!);
        } on ApiException {
          // Vẫn hỏng — lượt sau thử lại.
        }
      }
      // Mất mạng — im lặng, lượt sau thử lại.
    }
  }

  Future<void> _show(SosInboxItem item) async {
    final emergency = item.urgency == 'emergency';
    await _plugin.show(
      item.notificationId.hashCode & 0x7fffffff,
      item.title,
      item.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          _channel.id,
          _channel.name,
          channelDescription: _channel.description,
          importance: Importance.max,
          priority: emergency ? Priority.max : Priority.high,
          category: AndroidNotificationCategory.call,
          color: const Color(0xFFDC2626),
          styleInformation: BigTextStyleInformation(item.body),
        ),
      ),
      payload: item.eventId,
    );
  }

  /// Bỏ một lời kêu gọi khỏi danh sách sau khi người dùng đã trả lời.
  void markAnswered(String notificationId) {
    pending.value = pending.value
        .where((i) => i.notificationId != notificationId)
        .toList();
    _plugin.cancel(notificationId.hashCode & 0x7fffffff);
  }
}
